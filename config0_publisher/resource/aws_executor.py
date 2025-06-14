#!/usr/bin/env python
"""
AWS Asynchronous Execution Module for Config0

This module provides utilities for executing infrastructure operations
asynchronously via AWS Lambda and CodeBuild services. It includes a decorator
for handling execution and a class that serves as an interface to these services.

The module is designed to work with Config0's resource management system to
track and monitor asynchronous operations in AWS.
"""

# Copyright 2025 Gary Leong gary@config0.com
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import functools
import uuid
import json
import os
import boto3
import logging
import time
import hashlib

# Configure logging to suppress boto3/botocore debug messages
logging.getLogger('botocore').setLevel(logging.WARNING)
logging.getLogger('boto3').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)

from config0_publisher.loggerly import Config0Logger

def _delete_s3_object(s3_client, bucket, key):
    """
    Safely delete an object from S3 with error handling
    
    Args:
        bucket (str): S3 bucket name
        key (str): Object key to delete
    Returns:
        bool: True if deletion was successful, False otherwise
    """
    try:
        s3_client.delete_object(Bucket=bucket, Key=key)
        print(f"Deleted S3 object s3://{bucket}/{key}")
        return True
    except Exception as e:
        print(f"WARNING: Failed to delete S3 object s3://{bucket}/{key}: {str(e)}")
        return False

def _s3_put_object(s3_client, bucket, key, body, content_type='text/plain'):
    """
    Put an object to S3, handling errors gracefully
    """
    if not bucket or not key:
        return False
    
    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type
        )
        print(f"Successfully wrote to S3: s3://{bucket}/{key}")
        return True
    except Exception as e:
        print(f"Failed to write to S3: s3://{bucket}/{key} - {str(e)}")
        return False

def _s3_get_object(s3_client, bucket, key):
    """
    Fetch an object from S3 and return its content.
    - JSON (application/json): Parsed JSON (dict or list).
    - Plain text (text/plain): Integer if valid, otherwise string.
    - Other content types: Raw bytes.
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content_type = response.get('ContentType', '')
        content = response['Body'].read()

        if content_type == 'application/json':
            return json.loads(content.decode('utf-8'))
        
        if content_type in ['text/plain', 'application/octet-stream']:
            decoded = content.decode('utf-8').strip()
            return int(decoded) if decoded.lstrip('-+').isdigit() else decoded

        return content  # Return raw bytes for other content types

    except Exception as e:
        print(f"Error fetching object: {e}")
        return False

def get_execution_status(execution_id=None, output_bucket=None):
    """
    Get the status of an execution from S3 using initiated and done markers.

    Args:
        execution_id (str, optional): Execution ID to check
        output_bucket (str, optional): S3 bucket where execution data is stored

    Returns:
        dict: Status information for the execution
    """

    # Initialize result structure
    result = {
        "execution_id": execution_id,
        "initiated": False,
        "done": False,
        "status": False,
        "expired": False
    }

    s3_client = boto3.client('s3')

    # Check for initiated marker
    initiated_key = f"executions/{execution_id}/initiated"
    try:
        result["t0"] = int(_s3_get_object(s3_client, output_bucket, initiated_key))
        if result.get("t0"):
            result["initiated"] = True
        else:
            del result["t0"]
    except:
        result["initiated"] = False
        return result

    if not result.get("initiated"):
        return result

    expire_at_key = f"executions/{execution_id}/expire_at"
    try:
        expire_at = int(_s3_get_object(s3_client, output_bucket, expire_at_key))
        if int(time.time()) > expire_at:
            result["expired"] = True
    except:
        result["expired"] = False

    if result.get("expired"):
        return result

    status_key = f"executions/{execution_id}/status.json"
    try:
        result["status"] = _s3_get_object(s3_client, output_bucket, status_key)
        if not result.get("status"):
            del result["status"]
    except:
        result["status"] = False

    # Check for done marker
    done_key = f"executions/{execution_id}/done"
    try:
       result["t1"] = int(_s3_get_object(s3_client, output_bucket, done_key))
       if result.get("t1"):
           result["done"] = True
       else:
           del result["t1"]
    except:
       result["done"] = False

    if result.get("done"):
        result["results"] = _s3_get_object(s3_client,
                                           output_bucket,
                                           result["result_key"])

    return result

def aws_executor(execution_type="lambda"):
    """
    Decorator that handles asynchronous execution through AWS Lambda or CodeBuild.
    
    This decorator is designed to work with Config0's resource management system.
    It implements the async execution pattern with execution tracking via S3.
    
    Args:
        execution_type: "lambda" or "codebuild" 
        
    Returns:
        Decorator function that handles the execution
    """
    def decorator(func):
        @functools.wraps(func)
       
        def wrapper(self, **kwargs):

            s3_client = boto3.client('s3')

            # Initialize logger
            logger = Config0Logger("AWSExecutor", logcategory="cloudprovider")
            logger.debug(f"Starting {execution_type} execution with {func.__name__}")

            # Get resource identifiers
            resource_type = getattr(self, 'resource_type', 'unknown')
            resource_id = getattr(self, 'resource_id', 'unknown')
            method = kwargs.get('method') or getattr(self, 'method', 'unknown')
            
            # Get timeout settings from build environment variables or environment
            build_env_vars = kwargs.get('build_env_vars') or getattr(self, 'build_env_vars', {})
            max_execution_time = None
            
            # Try to get timeout from build_env_vars
            if isinstance(build_env_vars, dict):
                if build_env_vars.get('BUILD_TIMEOUT'):
                    try:
                        max_execution_time = int(build_env_vars.get('BUILD_TIMEOUT'))
                        logger.debug(f"Using timeout from build_env_vars BUILD_TIMEOUT: {max_execution_time}s")
                    except (ValueError, TypeError):
                        pass
                
            # If not found in build_env_vars, try environment variables
            if not max_execution_time:
                if os.environ.get('BUILD_TIMEOUT'):
                    try:
                        max_execution_time = int(os.environ.get('BUILD_TIMEOUT'))
                        logger.debug(f"Using timeout from env BUILD_TIMEOUT: {max_execution_time}s")
                    except (ValueError, TypeError):
                        pass

            # Finally, allow explicit override
            if kwargs.get('max_execution_time'):
                max_execution_time = kwargs.get('max_execution_time')
                logger.debug(f"Using explicitly provided timeout: {max_execution_time}s")
            
            # If still no timeout, use defaults based on execution_type
            if not max_execution_time:
                if execution_type.lower() == "lambda":
                    max_execution_time = 900  # 15 minutes default for Lambda
                    logger.debug(f"Using default Lambda timeout: {max_execution_time}s")
                else:  # codebuild or anything else
                    max_execution_time = 3600  # 1 hour default for CodeBuild
                    logger.debug(f"Using default CodeBuild timeout: {max_execution_time}s")
            
            # Calculate build expiration time
            build_expire_at = int(time.time()) + int(max_execution_time)
            existing_run = self.check_execution_status()

            if existing_run.get("done"):
                existing_run["status"]["done"] = True
                return _s3_get_object(s3_client, self.output_bucket, initiated_key)
                return existing_run["status"]

            if existing_run.get("status"):
                existing_run["status"]["in_progress"] = True
                return existing_run["status"]

            # Prepare the payload from kwargs
            payload = {
                'execution_id': self.execution_id,
                'output_bucket': self.output_bucket,
                'params': kwargs
            }
            
            # Add class attributes if available
            for attr in ['resource_type', 'resource_id', 'stateful_id', 'method', 
                         'aws_region', 'version', 'binary', 'build_timeout',
                         'app_dir', 'app_name', 'remote_stateful_bucket']:
                if hasattr(self, attr):
                    payload[attr] = getattr(self, attr)

            s3_client = boto3.client('s3')
            s3_client.put_object(Bucket=self.output_bucket, Key=f"executions/{self.execution_id}/initiated", Body=str(time.time()))

            # Execute based on type
            if execution_type.lower() == "lambda":
                # Get Lambda function details - only use FunctionName from invocation_config
                function_name = kwargs.get('FunctionName') or getattr(self, 'lambda_function_name', 'config0-iac')
                lambda_region = getattr(self, 'lambda_region', 'us-east-1')
                
                # Initialize Lambda client with specific region for Lambda
                lambda_client = boto3.client('lambda', region_name=lambda_region)
                
                try:
                    # Check if this is a pre-configured payload from Lambdabuild
                    if kwargs.get('Payload'):
                        # If it's a string, assume it's already JSON formatted
                        if isinstance(kwargs['Payload'], str):
                            try:
                                payload_obj = json.loads(kwargs['Payload'])
                                # Ensure payload is a dict
                                if not isinstance(payload_obj, dict):
                                    payload_obj = {}
                            except:
                                payload_obj = {}
                        else:
                            # If it's already a dict, use it directly
                            payload_obj = kwargs['Payload']
                            
                        # Add tracking info if not already present
                        payload_obj['execution_id'] = self.execution_id
                        payload_obj['output_bucket'] = self.output_bucket
                            
                        lambda_payload = json.dumps(payload_obj)
                    else:
                        # Use our standard payload format
                        lambda_payload = json.dumps(payload)
                    
                    # Prepare Lambda invocation parameters - always use Event mode
                    lambda_params = {
                        'FunctionName': function_name,
                        'InvocationType': 'Event',  # Always async
                        'Payload': lambda_payload
                    }
                    
                    # LogType is omitted as it's not needed for Event invocations
                    
                    # Invoke Lambda function
                    response = lambda_client.invoke(**lambda_params)
                    
                    # Check response status
                    status_code = response.get('StatusCode')
                    
                    # For Event invocation type, 202 Accepted is expected
                    if status_code != 202:
                        logger.error(f"Lambda invocation failed with status code: {status_code}")
                        
                        # Clean up initiated marker
                        _delete_s3_object(s3_client, self.output_bucket, f"executions/{self.execution_id}/initiated")
                        
                        return {
                            'status': False,
                            'execution_id': self.execution_id,
                            'output_bucket': self.output_bucket,
                            'error': f"Lambda invocation failed with status code: {status_code}",
                            'output': f"Failed to invoke Lambda function {function_name} in region {lambda_region}"
                        }
                    
                except Exception as e:
                    logger.error(f"Lambda invocation failed with exception: {str(e)}")
                    
                    # Clean up initiated marker
                    _delete_s3_object(s3_client, self.output_bucket, f"executions/{self.execution_id}/initiated")
                    
                    return {
                        'status': False,
                        'execution_id': self.execution_id,
                        'output_bucket': self.output_bucket,
                        'error': f"Lambda invocation failed with exception: {str(e)}",
                        'output': f"Exception when invoking Lambda function {function_name} in region {lambda_region}: {str(e)}"
                    }
                    
            elif execution_type.lower() == "codebuild":
                # Start with all the original parameters from the Codebuild class
                build_params = dict(kwargs)
                
                # Get the project name
                project_name = build_params.get('projectName') or getattr(self, 'codebuild_project_name', 'config0-iac')
                build_params['projectName'] = project_name
                
                # Handle environment variables - ensure tracking vars are included
                if 'environmentVariablesOverride' in build_params:
                    env_vars = build_params['environmentVariablesOverride']
                else:
                    env_vars = []
                    build_params['environmentVariablesOverride'] = env_vars
                
                # Check for and add execution tracking variables if needed
                execution_id_found = False
                output_bucket_found = False
                
                for env_var in env_vars:
                    if env_var.get('name') == 'EXECUTION_ID':
                        execution_id_found = True
                    elif env_var.get('name') == 'OUTPUT_BUCKET':
                        output_bucket_found = True
                
                # Add execution_id if not present
                if not execution_id_found:
                    env_vars.append({
                        'name': 'EXECUTION_ID',
                        'value': self.execution_id
                    })
                
                # Add output_bucket if not present
                if not output_bucket_found:
                    env_vars.append({
                        'name': 'OUTPUT_BUCKET',
                        'value': self.output_bucket
                    })
                
                # Remove any parameters that aren't valid for CodeBuild API
                for key in list(build_params.keys()):
                    if key not in [
                        'projectName', 'environmentVariablesOverride', 
                        'timeoutInMinutesOverride', 'imageOverride', 
                        'computeTypeOverride', 'environmentTypeOverride',
                        'buildspecOverride'
                    ]:
                        del build_params[key]
                
                # Use the infrastructure region for CodeBuild
                codebuild_region = getattr(self, 'aws_region', 'us-east-1')
                
                # Initialize CodeBuild client with infrastructure region
                codebuild_client = boto3.client('codebuild', region_name=codebuild_region)
                
                try:
                    # Start the build
                    response = codebuild_client.start_build(**build_params)
                    
                    # Extract build information
                    build = response.get('build', {})
                    build_id = build.get('id')
                    
                    if not build_id:
                        logger.error("Failed to start CodeBuild project")
                        
                        # Clean up initiated marker
                        _delete_s3_object(s3_client, self.output_bucket, f"executions/{self.execution_id}/initiated")
                        
                        return {
                            'status': False,
                            'execution_id': self.execution_id,
                            'output_bucket': self.output_bucket,
                            'error': "Failed to start CodeBuild project",
                            'output': f"Failed to start CodeBuild project {project_name} in region {codebuild_region}"
                        }
                    
                    # Add build ID to payload
                    payload['build_id'] = build_id
                    s3_client.put_object(Bucket=self.output_bucket, Key=f"executions/{self.execution_id}/initiated", Body=str(int(time.time())))

                except Exception as e:
                    logger.error(f"CodeBuild start failed with exception: {str(e)}")
                    
                    # Clean up initiated marker
                    _delete_s3_object(s3_client, self.output_bucket, f"executions/{self.execution_id}/initiated")
                    
                    return {
                        'status': False,
                        'execution_id': self.execution_id,
                        'output_bucket': self.output_bucket,
                        'error': f"CodeBuild start failed with exception: {str(e)}",
                        'output': f"Exception when starting CodeBuild project {project_name} in region {codebuild_region}: {str(e)}"
                    }
                
            else:
                # Clean up initiated marker
                _delete_s3_object(s3_client, self.output_bucket, f"executions/{self.execution_id}/initiated")
                
                raise ValueError(f"Unsupported execution_type: {execution_type}")
            
            # Prepare result with tracking information
            result = {
                'status': True,
                'execution_id': self.execution_id,
                'output_bucket': self.output_bucket,
                'execution_type': execution_type,
                'initiated_key': f"executions/{self.execution_id}/initiated",
                'result_key': f"executions/{self.execution_id}/result.json",
                'done_key': f"executions/{self.execution_id}/done",
                'status_key': f"executions/{self.execution_id}/status.json",
                'build_expire_at': build_expire_at,
                'phases': True
            }

            _s3_put_object(s3_client,
                           self.output_bucket,
                           f"executions/{self.execution_id}/status.json",
                           json.dumps(result),
                           content_type='application/json')

            result['output'] = f"Initiated {execution_type} execution with ID: {self.execution_id}"

            # Add build ID for CodeBuild if available
            if execution_type.lower() == "codebuild" and 'build_id' in locals():
                result['build_id'] = build_id
            
            return result
        return wrapper
    return decorator

class AWSAsyncExecutor:
    """
    AWS Asynchronous Execution Manager for infrastructure operations.
    
    This class provides methods for executing infrastructure operations through 
    AWS Lambda or CodeBuild with consistent tracking and monitoring.
    
    It's designed to handle various types of infrastructure resources including
    Terraform modules, CloudFormation templates, and other IaC components.
    
    Attributes:
        resource_type (str): Type of infrastructure resource
        resource_id (str): Identifier for the specific resource
        lambda_function_name (str): AWS Lambda function name for lambda execution
        lambda_region (str): AWS region where Lambda function is located
        codebuild_project_name (str): AWS CodeBuild project name for codebuild execution
        tmp_bucket (str): S3 bucket for storing execution results
        output_bucket (str): S3 bucket for storing execution results (alias for tmp_bucket)
        execution_id (str): Deterministic or provided execution ID
    """
    
    # Class-level defaults
    lambda_function_name = os.environ.get("LAMBDA_FUNCTION_NAME", "config0-iac")
    lambda_region = os.environ.get("LAMBDA_REGION", "us-east-1")  # Default to us-east-1 for Lambda
    codebuild_project_name = os.environ.get("CODEBUILD_PROJECT_NAME", "config0-iac")
    
    def __init__(self, resource_type, resource_id, execution_id, output_bucket, **kwargs):
        """
        Initialize a new AWS Async Executor.
        
        Args:
            resource_type (str): Type of infrastructure resource (terraform, cloudformation, etc.)
            resource_id (str): Identifier for the specific resource
            execution_id (str): Execution ID for tracking
            output_bucket (str): S3 bucket for execution tracking
            **kwargs: Additional attributes to configure the execution environment
                - stateful_id: Stateful resource identifier
                - method: Operation method (create, destroy, etc.)
                - aws_region: AWS region for the infrastructure operation
                - lambda_region: AWS region for the Lambda function (defaults to us-east-1)
                - app_dir: Application directory
                - app_name: Application name
                - remote_stateful_bucket: S3 bucket for state storage
                - build_timeout: Maximum execution time in seconds
        """
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.execution_id = execution_id
        self.output_bucket = output_bucket
        self.tmp_bucket = self.output_bucket

        # Set additional attributes from kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)
            
        # Ensure lambda_region is set to us-east-1 unless explicitly overridden
        if not hasattr(self, "lambda_region"):
            self.lambda_region = self.__class__.lambda_region

    def clear_execution(self):
        """
        Clear all S3 objects related to a specific execution.

        Returns:
            int: Number of objects deleted, or -1 if an error occurred
        """
        logger = Config0Logger("AWSExecutor", logcategory="cloudprovider")
        
        try:
            # Delete entire execution directory from S3
            s3_client = boto3.client('s3')
            execution_prefix = f"executions/{self.execution_id}/"
            
            logger.info(f"Deleting execution directory for {self.execution_id}")
            
            # List all objects with the execution prefix
            paginator = s3_client.get_paginator('list_objects_v2')
            objects_to_delete = []
            
            # Collect all objects with the execution prefix
            for page in paginator.paginate(Bucket=self.output_bucket, Prefix=execution_prefix):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        objects_to_delete.append({'Key': obj['Key']})
            
            # Delete all objects if any were found
            if objects_to_delete:
                s3_client.delete_objects(
                    Bucket=self.output_bucket,
                    Delete={'Objects': objects_to_delete}
                )
                logger.info(f"Deleted {len(objects_to_delete)} objects from execution directory")
                return len(objects_to_delete)
            else:
                logger.info(f"No existing objects found for execution {self.execution_id}")
                return 0
                
        except Exception as e:
            logger.error(f"Failed to delete execution directory: {str(e)}")
            return -1
    
    @aws_executor(execution_type="lambda")
    def exec_lambda(self, **kwargs):
        """
        Execute infrastructure operation through AWS Lambda.
        
        Executes the operation asynchronously via AWS Lambda, which is suitable
        for operations that complete within the Lambda execution time limit.
        
        This method can handle both direct parameters and a pre-configured invocation
        configuration from Lambdabuild.
        
        Args:
            **kwargs: Operation parameters including:
                - method: Operation method (create, destroy, etc.)
                - build_env_vars: Environment variables for the build
                - ssm_name: SSM parameter name (if applicable)

                Or Lambdabuild invocation configuration:
                - FunctionName: Lambda function name
                - Payload: JSON payload or string with commands and environment variables
                
        Returns:
            dict: Execution tracking information with:
                - status: True if execution started successfully
                - execution_id: Unique identifier for the execution
                - output_bucket: S3 bucket for tracking
                - execution_type: "lambda"
                - initiated_key: bucket key to the initiated marker
                - result_key: bucket key to retrieve execution results
                - done_key: bucket key to the done marker
                - logs_key: bucket key to retrieve execution logs
        """
        pass  # Implementation handled by decorator
    
    @aws_executor(execution_type="codebuild")
    def exec_codebuild(self, **kwargs):
        """
        Execute infrastructure operation through AWS CodeBuild.
        
        Executes the operation asynchronously via AWS CodeBuild, which is suitable
        for longer-running operations that exceed Lambda execution time limits.
        
        This method can handle both direct parameters and a pre-configured build
        specification from Codebuild.
        
        Args:
            **kwargs: Operation parameters including:
                - method: Operation method (create, destroy, etc.)
                - build_env_vars: Environment variables for the build
                - ssm_name: SSM parameter name (if applicable)

                Or Codebuild build configuration:
                - projectName: CodeBuild project name
                - environmentVariablesOverride: Environment variables in CodeBuild format
                - timeoutInMinutesOverride: Build timeout in minutes
                - imageOverride: Docker image to use
                - computeTypeOverride: Compute resources to use
                - environmentTypeOverride: Environment type
                - buildspecOverride: Alternative buildspec file
                
        Returns:
            dict: Execution tracking information with:
                - status: True if execution started successfully
                - execution_id: Unique identifier for the execution
                - output_bucket: S3 bucket for tracking
                - execution_type: "codebuild"
                - build_id: CodeBuild build ID
                - initiated_key: bucket key to the initiated marker
                - result_key: bucket key to retrieve execution results
                - done_key: bucket key to the done marker
                - logs_key: bucket key to retrieve execution logs
        """
        pass  # Implementation handled by decorator
    
    def check_execution_status(self):
        return get_execution_status(self.execution_id,self.output_bucket)