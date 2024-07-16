import os
import csv
import json
import shutil
import zipfile
import logging
from datetime import datetime
from io import BytesIO

import boto3
import requests
import pandas as pd
from sqlalchemy import create_engine, Table, Column, Integer, String, Date, MetaData
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.engine.reflection import Inspector


# Custom exceptions
class UnableToGetFileInfoError(Exception):
    pass
class FileDownloadError(Exception):
    pass
class FailedToProcessCSVError(Exception):
    pass
class UnableToCreateTableError(Exception):
    pass
class NoDataInFileError(Exception):
    pass


class FileProcessor:
    """ Responsible for processing a CSV and storing it into our Database"""

    # Idealmente essas configs devem ser recebidas de uma Database
    _TMP_FILE_PATH = "/tmp/"
    _VEHICLES = ['automovel', 'bicicleta', 'caminhao', 'moto', 'onibus']
    _BULK_SIZE = 500

    def __init__(self, s3_client, bucket_name, event, table_name, engine):
        self.event = event
        self.engine = engine
        self.s3_client = s3_client
        self.table_name = table_name
        self.bucket_name = bucket_name

        self._table = None
        self.file_name = None
        self.insertion_date = None

    def execute(self):
        """ Executes all the processes in this class """

        try:
            # if not os.path.exists(self._TMP_FILE_PATH):
            #     os.makedirs(self._TMP_FILE_PATH)

            logging.info(f"Received event: {self.event}")

            try:
                self.file_name = self._get_file_info()
            except Exception:
                logging.error(f'Erro ao acessar dados recebidos no body do request: {self.event["body"]}')
                raise UnableToGetFileInfoError(f'Erro ao acessar dados recebidos no body do request: {self.event["body"]}')

            try:
                file_path = self._download_csv_file(self.file_name)
            except Exception as e:
                logging.error(f'Erro ao baixar arquivo da URL: {e}')
                raise FileDownloadError(f'Erro ao baixar arquivo da URL: {e}')

            try:
                df = self._process_csv(file_path)
            except Exception as e:
                logging.error(f'Erro ao tratar dados do CSV: {e}')
                raise FailedToProcessCSVError(f'Erro ao tratar dados do CSV: {e}')

            self._insert_into_rds(df)

        finally:
            pass
            # shutil.rmtree(self._TMP_FILE_PATH)
            
    def _get_file_info(self):
        """ Get the information about the file received in the url"""

        body = json.loads(self.event['body'])
        s3_url = body['s3_url']
        file_name = s3_url.split('/')[-1]

        return file_name

    def _download_csv_file(self, file_name):
        """ Download the file from the received url """

        file_path = self._TMP_FILE_PATH + file_name
        with open(file_path, 'wb') as f:
            self.s3_client.download_fileobj(self.bucket_name, file_name, f)

        return file_path

    def _process_csv(self, file_path):
        """ Process CSV file data """

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        df = pd.read_csv(file_path, delimiter=';', encoding='latin1')
        results = []

        for vehicle in self._VEHICLES:
        # NOTE Valores podem nao ser confiáveis, pois se por exemplo houve um acidente entre um
        # NOTE automovel e uma moto com o total de 1 morte esta uma morte será contabilizada tanto para moto 
        # NOTE quanto para automovel. Mas não há como saber para qual dos envolvidos atribuir a fatalidade
            result =  df[df[vehicle] >= 1].groupby(['trecho'])['mortos'].sum().reset_index(name=vehicle)
            results.append(result)

        df = results[0]
        for result in results[1:]:
            df = pd.merge(df, result, on=['trecho'],how='outer')

        # NOTE coluna 'created_at' está vinculada à data que os dados foram salvos na DB e não à ocorrência
        df['created_at'] = today
        df = pd.melt(df, id_vars=['created_at', 'trecho'], var_name='vehicle', value_name='number_deaths')
        df.rename(columns={'trecho': 'road_name'}, inplace=True)
        df = df.fillna(0)
        df['number_deaths'] = df['number_deaths'].astype(int)

        return df

    def _insert_into_rds(self, df):
        """ Insert dataframe data into the RDS"""

        batch = []

        try:
            self._create_table_if_not_exists()
        except Exception as e:
            logging.error(f'Erro ao processar verificacao e criacao da tabela {self.table_name}. {e}')
            raise UnableToCreateTableError(f'Erro ao processar verificacao e criacao da tabela {self.table_name}. {e}')

        list_reports = df.to_dict(orient='records')

        if not len(list_reports):
            logging.error(f'Arquivo {self.file_name} nao possui registros')
            raise NoDataInFileError(f'Arquivo {self.file_name} nao possui registros')

        self.insertion_date = list_reports[0]['created_at']
        try:
            with self.engine.connect() as connection:
                for item in list_reports:
                    batch.append(item)

                    if len(batch) >= self._BULK_SIZE:
                        self._execute_batch_insert(connection, batch)
                        batch = []

                if batch:
                    self._execute_batch_insert(connection, batch)

        except Exception as e:
            logging.error(f'Erro ao inserir dados na database. {e}')
            raise ConnectionError(f'Erro ao inserir dados na database. {e}')

    def _execute_batch_insert(self, connection, batch):
        """ Insert the itens in this bath into the DB """

        insert_statement = insert(self._table).values(batch)
        upsert_statement = insert_statement.on_duplicate_key_update(
            number_deaths=insert_statement.inserted.number_deaths
        )

        connection.execute(upsert_statement)
        connection.commit()

    def _create_table_if_not_exists(self):
        """ Verify if table exists before trying to insert values """

        inspector = Inspector.from_engine(self.engine)
        table_exists = inspector.has_table(self.table_name)

        if table_exists:
            metadata = MetaData()
            self._table = Table(self.table_name, metadata, autoload_with=self.engine)
        else:
            
            self._table = Table(self.table_name, metadata,
                        Column('created_at', Date, primary_key=True),
                        Column('road_name', String(50), primary_key=True),
                        Column('vehicle', String(50), primary_key=True),
                        Column('number_deaths', Integer))

        metadata.create_all(self.engine)

def process_csv(event, context):
    """ Lambda function for processing CSV file and inserting data into RDS """

    db_uri = os.getenv('DB_URI')
    bucket_name = os.getenv('S3_BUCKET_NAME')
    aws_access_key_id = os.getenv('KEY_ID')
    aws_secret_access_key = os.getenv('KEY')
    
    s3 = boto3.client('s3', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)

    try:
        table_name = 'traffic_accident_report'
        engine = create_engine(db_uri)
        action = FileProcessor(s3, bucket_name, event, table_name, engine)
        action.execute()
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
    
    return {
        'statusCode': 200,
        'body': json.dumps({'message': f"Processado e inserido dados do arquivo '{action.file_name}' com sucesso na tabela '{table_name}'. 'created_at' registrado na tabela {action.insertion_date}"})
    }


#-------------------------------------------------


# Custom exceptions
class NotAllowedExtensionError(Exception):
    pass
class ReceivedMultipleFilesError(Exception):
    pass
class FileDownloadError(Exception):
    pass
class FailedToReadCSVError(Exception):
    pass
class S3UploadError(Exception):
    pass


class FileDownloader:
    """ Responsible for downloading files and saving into the S3 Bucket """

    _ALLOWED_EXTENSIONS = ['csv', 'zip']
    _TMP_FILE_PATH = "/tmp"
    _COLUMNS = [
        'data',
        'trecho',
        'automovel',
        'bicicleta',
        'caminhao',
        'moto',
        'onibus',
        'mortos'
    ]


    def __init__(self, s3_client, bucket_name, event):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.event = event

        self.s3_url = None

    def execute(self):
        """ Executes all the processes in this class """

        try:
            # if not os.path.exists(self._TMP_FILE_PATH):
            #     os.makedirs(self._TMP_FILE_PATH)

            self._file_name, self._file_extension, self._url = self._get_file_info()
            if self._file_extension not in self._ALLOWED_EXTENSIONS:
                logging.error(f'Arquivo {self._file_name} possui uma extensao invalida para este processo')
                raise NotAllowedExtensionError(f'Arquivo {self._file_name} possui uma extensao invalida para este processo') 
            
            try:
                # self._download_and_unzip_file()
                self.upload_csv_to_s3()
                self.s3_url = f"https://{self.bucket_name}.s3.{self.s3_client.meta.region_name}.amazonaws.com/{self._file_name}"
            except Exception:
                logging.error(f'Nao foi possivel fazer o download do arquivo {self._file_name}')
                raise FileDownloadError(f'Nao foi possivel fazer o download do arquivo {self._file_name}')

            # downloaded_files = os.listdir(self._TMP_FILE_PATH)
            # if len(downloaded_files) > 1:
            #     logging.error(f'Foram recebidos {len(downloaded_files)} arquivos para processamento. Esperado 1 arquivo')
            #     raise ReceivedMultipleFilesError(f'Foram recebidos {len(downloaded_files)} arquivos para processamento. Esperado 1 arquivo')
            
            # downloaded_file, downloaded_file_path, downloaded_file_extension = self._get_downloaded_file_info(downloaded_files)
            # if downloaded_file_extension != 'csv':
            #     logging.error(f'Arquivo {downloaded_file} nao e um arquivo CSV')
            #     raise NotAllowedExtensionError(f'Arquivo {downloaded_file} nao e um arquivo CSV')

            # try:
            #     filtered_csv_path = self._filter_csv_columns(downloaded_file_path)
            # except Exception:
            #     logging.error(f'Erro ao ler o arquivo CSV: {self._file_name}')
            #     raise FailedToReadCSVError(f'Erro ao ler o arquivo CSV: {self._file_name}')
            # try:
            #     self._upload_to_s3(downloaded_file_path)
            #     self.s3_url = f"https://{self.bucket_name}.s3.{self.s3_client.meta.region_name}.amazonaws.com/{self._file_name}"
            # except Exception as e:
            #     logging.error(f'Falha ao enviar arquivo para o bucket S3')
            #     raise S3UploadError(f'Falha ao enviar arquivo para o bucket S3: {e}')

        finally:
            pass
            # shutil.rmtree(self._TMP_FILE_PATH)
            
    def upload_csv_to_s3(self):
        """ Read CSV from URL and upload to S3 """

        with requests.get(self._url, stream=True) as r:
            r.raise_for_status()
            buffer = BytesIO()
            for chunk in r.iter_content(chunk_size=8192):
                buffer.write(chunk)
            buffer.seek(0)

        self._file_name = datetime.now().strftime('%Y%m%d_') + self._file_name

        s3_key = f"{self._file_name}"
        self.s3_client.upload_fileobj(buffer, self.bucket_name, s3_key)

    def _get_file_info(self):
        """ Get the information about the file received in the url"""

        body = json.loads(self.event['body'])
        csv_url = body['url']
        file_name = csv_url.split('/')[-1]
        file_extension = file_name.split('.')[-1]

        return file_name, file_extension, csv_url

    def _download_and_unzip_file(self):
        """ Download the file from the received url """

        file_path = self._TMP_FILE_PATH + self._file_name

        with requests.get(self._url, stream=True) as r:
            r.raise_for_status()
            buffer = BytesIO()
            for chunk in r.iter_content(chunk_size=8192):
                buffer.write(chunk)
            buffer.seek(0)
        if self._file_extension == 'zip':
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(self._TMP_FILE_PATH)
            os.remove(file_path)

    def _get_downloaded_file_info(self, downloaded_files):
        """ Get info from the downloaded file """

        file = downloaded_files[0]
        downloaded_file_path = os.path.join(self._TMP_FILE_PATH, file)
        downloaded_file_extension = file.split('.')[-1]

        return file, downloaded_file_path, downloaded_file_extension

    #def _filter_csv_columns(self, file_path):
        """ Remove unecessary data from the csv file """

        filtered_data = []
        vehicles = self._COLUMNS[2:7]
        with open(file_path, mode='r', encoding='latin1') as file:
            reader = csv.DictReader(file, delimiter=';')
            
            for row in reader:
                filtered_row = {col: row[col] for col in self._COLUMNS}

                if any(filtered_row[col] != '0' for col in vehicles):
                    filtered_data.append(filtered_row)

        # Sobreescrevendo csv antigo
        with open(file_path, mode='w', encoding='latin1', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=self._COLUMNS, delimiter=';')
            writer.writeheader()
            writer.writerows(filtered_data)

        return file_path

    def _upload_to_s3(self, file_path):
        """ Send file to  S3 """

        self._file_name = datetime.now().strftime('%Y%m%d_') + self._file_name
        with open(file_path, 'rb') as file:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=self._file_name,
                Body=file
            )

def download_csv(event, context):
    bucket_name = os.getenv('S3_BUCKET_NAME')
    aws_access_key_id = os.getenv('KEY_ID')
    aws_secret_access_key = os.getenv('KEY')

    s3 = boto3.client('s3', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)

    try:
        action = FileDownloader(s3, bucket_name, event)
        action.execute()
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
    
    lambda_client = boto3.client('lambda')
    response = lambda_client.invoke(
        FunctionName=os.environ['PROCESS_CSV_LAMBDA_NAME'],
        InvocationType='Event',
        Payload=json.dumps({"s3_url": action.s3_url})
    )

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "CSV downloaded and process_csv function invoked.",
            "s3_url": action.s3_url,
            "response": response
        })
    }
