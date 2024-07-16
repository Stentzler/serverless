# Serverless

## 1 - Frameworks:
 - ```npm install -g serverless```

 - ```sudo apt-get install awscli```

 - ```serverless plugin install -n serverless-step-functions```

 - ```serverless plugin install -n serverless-python-requirements```

 - ```serverless plugin install -n serverless-dotenv-plugin```
  
## Como rodar o projeto:

2. **Gerar arquivo .env:** O arquivo deve conter as mesmas variáveis listadas no arquivo de exemplo, ou abaixo:
  - **DB_URI**= URI do banco de dados que as lambdas vão popular
  - **KEY_ID**= aws_access_key_id para se conectar à S3
  - **KEY**=    aws_secret_access_key para se conectar à S3
  
  - **STAGE**= ENV ou PROD
  - **REGION**= Região da AWS
  - **DB_INSTANCE_IDENTIFIER**= Identifier da isntancia RDS
  - **DB_ALLOCATED_STORAGE**= Lambda config
  - **DB_INSTANCE_CLASS**= Lambda config
  - **DB_ENGINE**= Tipo da db EX: mysql
  - **DB_MASTER_USERNAME**= Usuário da Database
  - **DB_MASTER_USER_PASSWORD**= Password Database
  - **DB_NAME**= nome Database
  - **S3_BUCKET_NAME**= Nome do bucket S3 que será utilizado

#
3. **RODAR LOCALMENTE**
 -  ```npm intall```
 -  ```pip install -r requirements.txt```
 -  ```npm install --save serverless-python-requirements```
 -  ```serverless deploy```
