import os
import json
import zipfile
import shutil
from datetime import datetime

import boto3
import requests
import pandas as pd

from common.config import configure_aws_session

configure_aws_session()


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
    _TMP_FILE_PATH = f"./tmp/"
    _COLUMNS = [
        'data',
        'horario',
        'km',
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
            if not os.path.exists(self._TMP_FILE_PATH):
                os.makedirs(self._TMP_FILE_PATH)

            self._file_name, self._file_extension, self._url = self._get_file_info()
            if self._file_extension not in self._ALLOWED_EXTENSIONS:
                raise NotAllowedExtensionError(f'Arquivo {self._file_name} possui uma extensao invalida para este processo') 
            
            try:
                self._download_and_unzip_file()
            except Exception:
                raise FileDownloadError(f'Nao foi possivel fazer o download do arquivo {self._file_name}')

            downloaded_files = os.listdir(self._TMP_FILE_PATH)
            if len(downloaded_files) > 1:
                raise ReceivedMultipleFilesError(f'Foram recebidos {len(downloaded_files)} arquivos para processamento. Esperado 1 arquivo')
            
            downloaded_file, downloaded_file_path, downloaded_file_extension = self._get_downloaded_file_info(downloaded_files)
            if downloaded_file_extension != 'csv':
                raise NotAllowedExtensionError(f'Arquivo {downloaded_file} nao e um arquivo CSV')

            try:
                filtered_csv_path = self._filter_csv_columns(downloaded_file_path)
            except Exception:
                raise FailedToReadCSVError(f'Erro ao ler o arquivo CSV: {self._file_name}')

            try:
                self._upload_to_s3(filtered_csv_path)
                self.s3_url = f"https://{self.bucket_name}.s3.{self.s3_client.meta.region_name}.amazonaws.com/{self._file_name}"
            except Exception:
                raise S3UploadError(f'Falha ao enviar arquivo para o bucket S3')

        finally:
            shutil.rmtree(self._TMP_FILE_PATH)

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
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

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

    def _filter_csv_columns(self, file_path):
        """ Remove unecessary data from the csv file """

        df = pd.read_csv(file_path, usecols=self._COLUMNS, delimiter=';', encoding='utf-8', dtype=str)

        # Removendo linhas que com meio de transporte que nao serao avaliados
        df = df[df[self._COLUMNS[4:]].eq('1').any(axis=1)]

        # Sobreescrevendo csv antigo
        df.to_csv(file_path, sep=';', encoding='utf-8', index=False)

        return file_path

    def _upload_to_s3(self, file_path):
        """ Send file to  S3 """

        self._file_name = datetime.now().strftime('%Y%m%d_') + self._file_name
        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=self._file_name,
            Body=open(file_path, 'rb')
        )


def download_csv(event, context):
    bucket_name = os.getenv('S3_BUCKET_NAME')
    aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
    aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')

    s3 = boto3.client('s3', aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)

    try:
        action = FileDownloader(s3, bucket_name, event)
        action.execute()
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
    
    return {
        'statusCode': 200,
        'body': json.dumps({'s3_url': action.s3_url})
    }
