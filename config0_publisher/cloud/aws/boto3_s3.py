#!/usr/bin/env python

import json
import boto3
import base64
import pickle
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
        #serialized_data = pickle.dumps(data)

        # Encode the serialized data to Base64
        #base64_data = base64.b64encode(json_data).decode('utf-8')
        base64_data = base64.b64encode(json_data.encode('utf-8')).decode('utf-8')

        # Upload the Base64 string to S3
        s3.put_object(Bucket=bucket_name,
                      Key=bucket_key,
                      Body=base64_data)

        print(f"Successfully uploaded {bucket_key} to {bucket_name}.")

    except (NoCredentialsError, ClientError) as e:
        print(f"Error uploading to S3: {e}")

def s3_to_dict(bucket_name, bucket_key):
    """
    Read a Base64 encoded file from an S3 bucket and convert it back to a dictionary.

    :param bucket_name: Name of the S3 bucket
    :param bucket_key: Name of the key to be read from S3
    :return: Dictionary read from S3
    """
    s3 = boto3.client('s3')

    try:
        # Get the object from S3
        response = s3.get_object(Bucket=bucket_name, Key=bucket_key)
        base64_data = response['Body'].read().decode('utf-8')

        # Decode the Base64 string
        #json_data = base64.b64decode(base64_data)
        json_data = base64.b64decode(base64_data).decode('utf-8')

        # Deserialize the data back to dictionary
        #data = pickle.loads(serialized_data)
        data = json.loads(json_data)

        return data

    except (NoCredentialsError, ClientError) as e:
        print(f"Error reading from S3: {e}")
        return None