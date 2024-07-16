import json

from dotenv import load_dotenv

from handler import download_csv
from handler import process_csv

def test_download_lambda():
    # Mock
    event = {
        "body": json.dumps({
            "url": "https://dados.antt.gov.br/dataset/ef0171a8-f0df-4817-a4ed-b4ff94d87194/resource/940fa31c-e30e-4a06-9953-4c8b491b2887/download/demostrativo_acidentes_viasul.csv"
        })
    }
    context = {}
    response = download_csv(event, context)
    print(response)

def test_process_file_lambda():
    # Mock
    event = {
        "body": json.dumps({
            "s3_url": "https://stentzler-serverless.s3.sa-east-1.amazonaws.com/20240714_demostrativo_acidentes_viasul.csv"
        })
    }
    context = {}
    
    response = process_csv(event, context)
    print(response)


if __name__ == "__main__":
    load_dotenv('./.env')
    # test_download_lambda()
    test_process_file_lambda()

#   POST - https://d23y2qzyzj.execute-api.sa-east-1.amazonaws.com/prod/download-csv
#   POST - https://d23y2qzyzj.execute-api.sa-east-1.amazonaws.com/prod/process-csv