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
            for attr in ['resource_type', 'resource_id', 'stateful_id', 'tmp_bucket']:
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
                function_name = getattr(self, 'lambda_function_name', 'iac-ci')
                
                # DEBUG
                print(f"DEBUG AWS_EXECUTOR: Invoking Lambda function: {function_name}")
                
                # Initialize Lambda client
                lambda_client = boto3.client('lambda')
                
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
                            'output': f"Failed to invoke Lambda function {function_name}"
                        }
                except Exception as e:
                    # DEBUG
                    print(f"DEBUG AWS_EXECUTOR: EXCEPTION during Lambda invocation: {str(e)}")
                    
                    logger.error(f"Lambda invocation failed with exception: {str(e)}")
                    return {
                        'status': False,
                        'error': f"Lambda invocation failed with exception: {str(e)}",
                        'output': f"Exception when invoking Lambda function {function_name}: {str(e)}"
                    }
                    
            elif execution_type.lower() == "codebuild":
                project_name = getattr(self, 'codebuild_project_name', 'iac-build')
                
                # DEBUG
                print(f"DEBUG AWS_EXECUTOR: Starting CodeBuild project: {project_name}")
                
                # Initialize CodeBuild client
                codebuild_client = boto3.client('codebuild')
                
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
                            'output': f"Failed to start CodeBuild project {project_name}"
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
                        'output': f"Exception when starting CodeBuild project {project_name}: {str(e)}"
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
                'output': f"Initiated {execution_type} execution with ID: {execution_id}"
            }
            
            # Add build ID for CodeBuild if available
            if execution_type.lower() == "codebuild" and 'build_id' in payload:
                result['build_id'] = payload['build_id']
            
            # DEBUG
            print("DEBUG AWS_EXECUTOR: Returning result:")
            for k, v in result.items():
                print(f"  {k}: {v}")
            print("*"*80 + "\n")
            
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
        codebuild_project_name (str): AWS CodeBuild project name for codebuild execution
        tmp_bucket (str): S3 bucket for storing execution results
    """
    
    # Class-level defaults
    lambda_function_name = os.environ.get("LAMBDA_FUNCTION_NAME", "iac-ci")
    codebuild_project_name = os.environ.get("CODEBUILD_PROJECT_NAME", "iac-build")
    
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
                - aws_region: AWS region for the operation
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