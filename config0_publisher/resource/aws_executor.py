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
            # Initialize logger
            logger = Config0Logger("AWSExecutor", logcategory="cloudprovider")

            # Get resource identifiers
            resource_type = getattr(self, 'resource_type', 'unknown')
            resource_id = getattr(self, 'resource_id', 'unknown')
            method = kwargs.get('method') or getattr(self, 'method', 'unknown')

            # Generate a deterministic execution ID based on resource identifiers
            # This allows checking for existing executions
            if kwargs.get('execution_id'):
                # Use provided execution_id if available
                execution_id = kwargs.get('execution_id')
            else:
                # Create a deterministic execution ID based on resource identifiers and timestamp
                base_string = f"{resource_type}:{resource_id}:{method}"

                if kwargs.get('force_new_execution') or getattr(self, 'force_new_execution', False):
                    # Add timestamp to force a new execution
                    base_string = f"{base_string}:{time.time()}"

                execution_id = hashlib.md5(base_string.encode()).hexdigest()

            # Get the required parameters
            s3_bucket = kwargs.get('tmp_bucket') or getattr(self, 'tmp_bucket', None)
            if not s3_bucket:
                raise ValueError("tmp_bucket must be provided as parameter or class attribute")

            # Check if execution is already in progress
            if not kwargs.get('force_new_execution') and not getattr(self, 'force_new_execution', False):
                try:
                    # Check if status file exists in S3
                    s3_client = boto3.client('s3')
                    status_key = f"executions/{execution_id}/status"

                    try:
                        status_obj = s3_client.get_object(Bucket=s3_bucket, Key=status_key)
                        status_data = json.loads(status_obj['Body'].read().decode('utf-8'))

                        # If status indicates execution is in progress, return info
                        if status_data.get('status') == 'in_progress':
                            logger.info(f"Execution already in progress for {resource_type}:{resource_id} with ID {execution_id}")
                            return {
                                'status': True,
                                'execution_id': execution_id,
                                's3_bucket': s3_bucket,
                                'execution_type': execution_type,
                                'status_url': f"s3://{s3_bucket}/executions/{execution_id}/status",
                                'result_url': f"s3://{s3_bucket}/executions/{execution_id}/result.json",
                                'logs_url': f"s3://{s3_bucket}/executions/{execution_id}/logs.txt",
                                'output': f"Execution already in progress with ID: {execution_id}",
                                'already_running': True
                            }
                    except s3_client.exceptions.NoSuchKey:
                        # Status file doesn't exist, proceed with new execution
                        pass
                    except Exception as e:
                        logger.warning(f"Error checking execution status: {str(e)}")
                        # Continue with execution if status check fails
                except Exception as e:
                    logger.warning(f"Error connecting to S3: {str(e)}")
                    # Continue with execution if S3 check fails
            
            # Prepare the payload from kwargs
            payload = {
                'execution_id': execution_id,
                's3_bucket': s3_bucket,
                'params': kwargs
            }
            
            # Add class attributes if available
            for attr in ['resource_type', 'resource_id', 'stateful_id', 'method', 
                         'aws_region', 'version', 'binary', 'build_timeout',
                         'app_dir', 'app_name', 'remote_stateful_bucket']:
                if hasattr(self, attr):
                    payload[attr] = getattr(self, attr)
            
            # Write initial status to S3
            try:
                s3_client = boto3.client('s3')
                status_data = {
                    'status': 'in_progress',
                    'start_time': time.time(),
                    'resource_type': resource_type,
                    'resource_id': resource_id,
                    'method': method,
                    'execution_type': execution_type
                }
                s3_client.put_object(
                    Bucket=s3_bucket,
                    Key=f"executions/{execution_id}/status",
                    Body=json.dumps(status_data),
                    ContentType='application/json'
                )
            except Exception as e:
                logger.warning(f"Failed to write initial status to S3: {str(e)}")
                # Continue even if status write fails
            
            # Execute based on type
            if execution_type.lower() == "lambda":
                # Use lambda_region (us-east-1) for Lambda invocations
                lambda_region = getattr(self, 'lambda_region', 'us-east-1')
                function_name = getattr(self, 'lambda_function_name', 'config0-iac')
                
                # Initialize Lambda client with specific region for Lambda
                lambda_client = boto3.client('lambda', region_name=lambda_region)
                
                try:
                    # Invoke Lambda function asynchronously
                    response = lambda_client.invoke(
                        FunctionName=function_name,
                        InvocationType='Event',
                        Payload=json.dumps(payload)
                    )
                    
                    # Check response status
                    status_code = response.get('StatusCode')
                    if status_code != 202:  # 202 Accepted is expected for async invocation
                        logger.error(f"Lambda invocation failed with status code: {status_code}")
                        
                        # Update status in S3
                        try:
                            status_data['status'] = 'failed'
                            status_data['end_time'] = time.time()
                            status_data['error'] = f"Lambda invocation failed with status code: {status_code}"
                            s3_client.put_object(
                                Bucket=s3_bucket,
                                Key=f"executions/{execution_id}/status",
                                Body=json.dumps(status_data),
                                ContentType='application/json'
                            )
                        except Exception as e:
                            logger.warning(f"Failed to update status in S3: {str(e)}")
                        
                        return {
                            'status': False,
                            'execution_id': execution_id,
                            's3_bucket': s3_bucket,
                            'error': f"Lambda invocation failed with status code: {status_code}",
                            'output': f"Failed to invoke Lambda function {function_name} in region {lambda_region}"
                        }
                except Exception as e:
                    logger.error(f"Lambda invocation failed with exception: {str(e)}")
                    
                    # Update status in S3
                    try:
                        status_data['status'] = 'failed'
                        status_data['end_time'] = time.time()
                        status_data['error'] = f"Lambda invocation failed with exception: {str(e)}"
                        s3_client.put_object(
                            Bucket=s3_bucket,
                            Key=f"executions/{execution_id}/status",
                            Body=json.dumps(status_data),
                            ContentType='application/json'
                        )
                    except Exception as se:
                        logger.warning(f"Failed to update status in S3: {str(se)}")
                    
                    return {
                        'status': False,
                        'execution_id': execution_id,
                        's3_bucket': s3_bucket,
                        'error': f"Lambda invocation failed with exception: {str(e)}",
                        'output': f"Exception when invoking Lambda function {function_name} in region {lambda_region}: {str(e)}"
                    }
                    
            elif execution_type.lower() == "codebuild":
                # Use the infrastructure region for CodeBuild
                codebuild_region = getattr(self, 'aws_region', 'us-east-1')
                project_name = getattr(self, 'codebuild_project_name', 'config0-iac')
                
                # Initialize CodeBuild client with infrastructure region
                codebuild_client = boto3.client('codebuild', region_name=codebuild_region)
                
                # Prepare environment variables for the build
                env_vars = [
                    {'name': 'EXECUTION_ID', 'value': execution_id},
                    {'name': 'S3_BUCKET', 'value': s3_bucket}
                ]
                
                # Add build environment variables if available
                if 'build_env_vars' in kwargs and kwargs['build_env_vars']:
                    for key, value in kwargs['build_env_vars'].items():
                        env_vars.append({
                            'name': key,
                            'value': str(value)
                        })
                
                try:
                    # Start the build
                    response = codebuild_client.start_build(
                        projectName=project_name,
                        environmentVariablesOverride=env_vars
                    )
                    
                    # Extract build information
                    build = response.get('build', {})
                    build_id = build.get('id')
                    
                    if not build_id:
                        logger.error("Failed to start CodeBuild project")
                        
                        # Update status in S3
                        try:
                            status_data['status'] = 'failed'
                            status_data['end_time'] = time.time()
                            status_data['error'] = "Failed to start CodeBuild project"
                            s3_client.put_object(
                                Bucket=s3_bucket,
                                Key=f"executions/{execution_id}/status",
                                Body=json.dumps(status_data),
                                ContentType='application/json'
                            )
                        except Exception as e:
                            logger.warning(f"Failed to update status in S3: {str(e)}")
                        
                        return {
                            'status': False,
                            'execution_id': execution_id,
                            's3_bucket': s3_bucket,
                            'error': "Failed to start CodeBuild project",
                            'output': f"Failed to start CodeBuild project {project_name} in region {codebuild_region}"
                        }
                    
                    # Add build ID to response
                    payload['build_id'] = build_id
                    status_data['build_id'] = build_id
                    
                    # Update status with build ID
                    try:
                        s3_client.put_object(
                            Bucket=s3_bucket,
                            Key=f"executions/{execution_id}/status",
                            Body=json.dumps(status_data),
                            ContentType='application/json'
                        )
                    except Exception as e:
                        logger.warning(f"Failed to update status with build ID in S3: {str(e)}")
                        
                except Exception as e:
                    logger.error(f"CodeBuild start failed with exception: {str(e)}")
                    
                    # Update status in S3
                    try:
                        status_data['status'] = 'failed'
                        status_data['end_time'] = time.time()
                        status_data['error'] = f"CodeBuild start failed with exception: {str(e)}"
                        s3_client.put_object(
                            Bucket=s3_bucket,
                            Key=f"executions/{execution_id}/status",
                            Body=json.dumps(status_data),
                            ContentType='application/json'
                        )
                    except Exception as se:
                        logger.warning(f"Failed to update status in S3: {str(se)}")
                    
                    return {
                        'status': False,
                        'execution_id': execution_id,
                        's3_bucket': s3_bucket,
                        'error': f"CodeBuild start failed with exception: {str(e)}",
                        'output': f"Exception when starting CodeBuild project {project_name} in region {codebuild_region}: {str(e)}"
                    }
                
            else:
                # Update status in S3
                try:
                    status_data['status'] = 'failed'
                    status_data['end_time'] = time.time()
                    status_data['error'] = f"Unsupported execution_type: {execution_type}"
                    s3_client.put_object(
                        Bucket=s3_bucket,
                        Key=f"executions/{execution_id}/status",
                        Body=json.dumps(status_data),
                        ContentType='application/json'
                    )
                except Exception as e:
                    logger.warning(f"Failed to update status in S3: {str(e)}")
                
                raise ValueError(f"Unsupported execution_type: {execution_type}")
            
            # Prepare result with tracking information
            result = {
                'status': True,
                'execution_id': execution_id,
                's3_bucket': s3_bucket,
                'execution_type': execution_type,
                'status_url': f"s3://{s3_bucket}/executions/{execution_id}/status",
                'result_url': f"s3://{s3_bucket}/executions/{execution_id}/result.json",
                'logs_url': f"s3://{s3_bucket}/executions/{execution_id}/logs.txt",
                'output': f"Initiated {execution_type} execution with ID: {execution_id}"
            }
            
            # Add build ID for CodeBuild if available
            if execution_type.lower() == "codebuild" and 'build_id' in payload:
                result['build_id'] = payload['build_id']
            
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
    """
    
    # Class-level defaults
    lambda_function_name = os.environ.get("LAMBDA_FUNCTION_NAME", "config0-iac")
    lambda_region = os.environ.get("LAMBDA_REGION", "us-east-1")  # Default to us-east-1 for Lambda
    codebuild_project_name = os.environ.get("CODEBUILD_PROJECT_NAME", "config0-iac")
    
    def __init__(self, resource_type, resource_id, **kwargs):
        """
        Initialize a new AWS Async Executor.
        
        Args:
            resource_type (str): Type of infrastructure resource (terraform, cloudformation, etc.)
            resource_id (str): Identifier for the specific resource
            **kwargs: Additional attributes to configure the execution environment
                - tmp_bucket: S3 bucket for execution tracking
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
        
        # Set additional attributes from kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)
            
        # Ensure lambda_region is set to us-east-1 unless explicitly overridden
        if not hasattr(self, "lambda_region"):
            self.lambda_region = self.__class__.lambda_region
    
    @aws_executor(execution_type="lambda")
    def exec_lambda(self, **kwargs):
        """
        Execute infrastructure operation through AWS Lambda.
        
        Executes the operation asynchronously via AWS Lambda, which is suitable
        for operations that complete within the Lambda execution time limit.
        
        Args:
            **kwargs: Operation parameters including:
                - method: Operation method (create, destroy, etc.)
                - build_env_vars: Environment variables for the build
                - ssm_name: SSM parameter name (if applicable)
                
        Returns:
            dict: Execution tracking information with:
                - status: True if execution started successfully
                - execution_id: Unique identifier for the execution
                - s3_bucket: S3 bucket for tracking
                - execution_type: "lambda"
                - status_url: URL to check execution status
                - result_url: URL to retrieve execution results
                - logs_url: URL to retrieve execution logs
        """
        pass  # Implementation handled by decorator
    
    @aws_executor(execution_type="codebuild")
    def exec_codebuild(self, **kwargs):
        """
        Execute infrastructure operation through AWS CodeBuild.
        
        Executes the operation asynchronously via AWS CodeBuild, which is suitable
        for longer-running operations that exceed Lambda execution time limits.
        
        Args:
            **kwargs: Operation parameters including:
                - method: Operation method (create, destroy, etc.)
                - build_env_vars: Environment variables for the build
                - ssm_name: SSM parameter name (if applicable)
                
        Returns:
            dict: Execution tracking information with:
                - status: True if execution started successfully
                - execution_id: Unique identifier for the execution
                - s3_bucket: S3 bucket for tracking
                - execution_type: "codebuild"
                - build_id: CodeBuild build ID
                - status_url: URL to check execution status
                - result_url: URL to retrieve execution results
                - logs_url: URL to retrieve execution logs
        """
        pass  # Implementation handled by decorator