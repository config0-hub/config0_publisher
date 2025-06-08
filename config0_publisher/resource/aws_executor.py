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
            
            # DEBUG START
            print("\n" + "*"*80)
            print(f"DEBUG AWS_EXECUTOR: Starting {execution_type} execution with {func.__name__}")
            print(f"DEBUG AWS_EXECUTOR: Self attributes:")
            for attr in ['resource_type', 'resource_id', 'stateful_id', 'tmp_bucket', 'lambda_region', 'aws_region']:
                if hasattr(self, attr):
                    print(f"  {attr}: {getattr(self, attr)}")
            print(f"DEBUG AWS_EXECUTOR: Input kwargs:")
            for k, v in kwargs.items():
                if k == "build_env_vars" and isinstance(v, dict):
                    print(f"  {k}: <dict with {len(v)} items>")
                else:
                    print(f"  {k}: {v}")
            # DEBUG END
            
            logger.debug(f"Starting {execution_type} execution with {func.__name__}")
            
            # Generate a unique execution ID
            execution_id = str(uuid.uuid4())
            
            # DEBUG
            print(f"DEBUG AWS_EXECUTOR: Generated execution_id: {execution_id}")
            
            # Get the required parameters
            s3_bucket = kwargs.get('tmp_bucket') or getattr(self, 'tmp_bucket', None)
            if not s3_bucket:
                # DEBUG
                print("DEBUG AWS_EXECUTOR: ERROR - tmp_bucket not provided")
                raise ValueError("tmp_bucket must be provided as parameter or class attribute")
            
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
            
            # DEBUG
            print(f"DEBUG AWS_EXECUTOR: Prepared payload with {len(payload)} items")
            
            # Execute based on type
            if execution_type.lower() == "lambda":
                # Use lambda_region (us-east-1) for Lambda invocations
                lambda_region = getattr(self, 'lambda_region', 'us-east-1')
                function_name = getattr(self, 'lambda_function_name', 'iac-ci')
                
                # DEBUG
                print(f"DEBUG AWS_EXECUTOR: Invoking Lambda function: {function_name} in region {lambda_region}")
                print(f"DEBUG AWS_EXECUTOR: Infrastructure region is: {getattr(self, 'aws_region', 'unknown')}")
                
                # Initialize Lambda client with specific region for Lambda
                lambda_client = boto3.client('lambda', region_name=lambda_region)
                
                try:
                    # Invoke Lambda function asynchronously
                    response = lambda_client.invoke(
                        FunctionName=function_name,
                        InvocationType='Event',
                        Payload=json.dumps(payload)
                    )
                    
                    # DEBUG
                    print(f"DEBUG AWS_EXECUTOR: Lambda response received:")
                    print(f"  StatusCode: {response.get('StatusCode')}")
                    
                    # Check response status
                    status_code = response.get('StatusCode')
                    if status_code != 202:  # 202 Accepted is expected for async invocation
                        # DEBUG
                        print(f"DEBUG AWS_EXECUTOR: ERROR - Lambda invocation failed with status code: {status_code}")
                        
                        logger.error(f"Lambda invocation failed with status code: {status_code}")
                        return {
                            'status': False,
                            'error': f"Lambda invocation failed with status code: {status_code}",
                            'output': f"Failed to invoke Lambda function {function_name} in region {lambda_region}"
                        }
                except Exception as e:
                    # DEBUG
                    print(f"DEBUG AWS_EXECUTOR: EXCEPTION during Lambda invocation: {str(e)}")
                    
                    logger.error(f"Lambda invocation failed with exception: {str(e)}")
                    return {
                        'status': False,
                        'error': f"Lambda invocation failed with exception: {str(e)}",
                        'output': f"Exception when invoking Lambda function {function_name} in region {lambda_region}: {str(e)}"
                    }
                    
            elif execution_type.lower() == "codebuild":
                # Use the infrastructure region for CodeBuild
                codebuild_region = getattr(self, 'aws_region', 'us-east-1')
                project_name = getattr(self, 'codebuild_project_name', 'iac-build')
                
                # DEBUG
                print(f"DEBUG AWS_EXECUTOR: Starting CodeBuild project: {project_name} in region {codebuild_region}")
                
                # Initialize CodeBuild client with infrastructure region
                codebuild_client = boto3.client('codebuild', region_name=codebuild_region)
                
                # Prepare environment variables for the build
                env_vars = [
                    {'name': 'EXECUTION_ID', 'value': execution_id},
                    {'name': 'S3_BUCKET', 'value': s3_bucket}
                ]
                
                # Add build environment variables if available
                if 'build_env_vars' in kwargs and kwargs['build_env_vars']:
                    # DEBUG
                    print(f"DEBUG AWS_EXECUTOR: Adding {len(kwargs['build_env_vars'])} build environment variables")
                    
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
                    
                    # DEBUG
                    print(f"DEBUG AWS_EXECUTOR: CodeBuild started with build ID: {build_id}")
                    
                    if not build_id:
                        # DEBUG
                        print("DEBUG AWS_EXECUTOR: ERROR - Failed to start CodeBuild project")
                        
                        logger.error("Failed to start CodeBuild project")
                        return {
                            'status': False,
                            'error': "Failed to start CodeBuild project",
                            'output': f"Failed to start CodeBuild project {project_name} in region {codebuild_region}"
                        }
                    
                    # Add build ID to response
                    payload['build_id'] = build_id
                except Exception as e:
                    # DEBUG
                    print(f"DEBUG AWS_EXECUTOR: EXCEPTION during CodeBuild start: {str(e)}")
                    
                    logger.error(f"CodeBuild start failed with exception: {str(e)}")
                    return {
                        'status': False,
                        'error': f"CodeBuild start failed with exception: {str(e)}",
                        'output': f"Exception when starting CodeBuild project {project_name} in region {codebuild_region}: {str(e)}"
                    }
                
            else:
                # DEBUG
                print(f"DEBUG AWS_EXECUTOR: ERROR - Unsupported execution_type: {execution_type}")
                
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
                'output': f"Initiate