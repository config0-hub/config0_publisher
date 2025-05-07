#!/usr/bin/env python

#import pickle
import json
import boto3
import base64
from botocore.exceptions import NoCredentialsError, ClientError

def dict_to_s3(data, bucket_name, bucket_key):
    """
    Write a dictionary to an S3 bucket as a Base64 encoded file.

    :param bucket_name: Name of the S3 bucket
    :param bucket_key: Name of the key to be created in S3
    :param data: Dictionary to be written to S3
    """
    s3 = boto3.client('s3')

    try:
        # Serialize the dictionary using pickle
        json_data = json.dumps(data)

        # Encode the serialized data to Base64
        base64_data = base64.b64encode(json_data.encode('utf-8')).decode('utf-8')

        # Upload the Base64 string to S3
        s3.put_object(Bucket=bucket_name,
                      Key=bucket_key,
                      Body=base64_data)

        print(f"Successfully uploaded {bucket_key} to {bucket_name}.")

    except (NoCredentialsError, ClientError) as e:
        print(f"Error uploading to S3: {e}")

