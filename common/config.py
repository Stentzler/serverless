import boto3


def configure_aws_session(region_name='sa-east-1'):
    boto3.setup_default_session(region_name=region_name)