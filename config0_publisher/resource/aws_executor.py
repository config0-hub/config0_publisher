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
            build_expire_at = time.time() + max_execution_time

            # Generate a deterministic execution ID based on resource identifiers
            if kwargs.get('execution_id'):
                # Use provided execution_id if available
                execution_id = kwargs.get('execution_id')
                logger.debug(f"Using provided execution_id: {execution_id}")
            else:
                # Create a deterministic execution ID based on resource identifiers
                base_string = f"{resource_type}:{resource_id}"
                execution_id = hashlib.md5(base_string.encode()).hexdigest()
                logger.debug(f"Generated deterministic execution_id: {execution_id} from {base_string}")

            # Determine output bucket with correct priority order
            output_bucket = None
            
            # 1. First check build_env_vars for OUTPUT_BUCKET
            if isinstance(build_env_vars, dict) and build_env_vars.get('OUTPUT_BUCKET'):
                output_bucket = build_env_vars.get('OUTPUT_BUCKET')
                logger.debug(f"Using OUTPUT_BUCKET from build_env_vars: {output_bucket}")
            
            # 2. Then check build_env_vars for TMP_BUCKET
            elif isinstance(build_env_vars, dict) and build_env_vars.get('TMP_BUCKET'):
                output_bucket = build_env_vars.get('TMP_BUCKET')
                logger.debug(f"Using TMP_BUCKET from build_env_vars: {output_bucket}")
            # 3. Check kwargs
            elif kwargs.get('output_bucket'):
                output_bucket = kwargs.get('output_bucket')

            # If no bucket found, raise error
            if not output_bucket:
                error_msg = "No S3 bucket specified for execution tracking. Please provide OUTPUT_BUCKET or TMP_BUCKET."
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Clear any existing execution files if specified
            if kwargs.get('clear_existing', False):
                self.clear_execution(execution_id, output_bucket)
            
            # Prepare the payload from kwargs
            payload = {
                'execution_id': execution_id,
                'output_bucket': output_bucket,
                'params': kwargs
            }
            
            # Add class attributes if available
            for attr in ['resource_type', 'resource_id', 'stateful_id', 'method', 
                         'aws_region', 'version', 'binary', 'build_timeout',
                         'app_dir', 'app_name', 'remote_stateful_bucket']:
                if hasattr(self, attr):
                    payload[attr] = getattr(self, attr)
            
            # Write initiated file to S3 to mark start of execution
            try:
                s3_client = boto3.client('s3')
                initiated_data = {
                    'start_time': time.time(),
                    'resource_type': resource_type,
                    'resource_id': resource_id,
                    'method': method,
                    'execution_type': execution_type,
                    'max_execution_time': max_execution_time
                }
                s3_client.put_object(
                    Bucket=output_bucket,
                    Key=f"executions/{execution_id}/initiated",
                    Body=json.dumps(initiated_data),
                    ContentType='application/json'
                )
                logger.debug(f"Created 'initiated' marker in S3 for execution {execution_id}")
            except Exception as e:
                logger.warning(f"Failed to write initiated marker to S3: {str(e)}")
                # Continue even if marker write fails
            
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
                        payload_obj['execution_id'] = execution_id
                        payload_obj['output_bucket'] = output_bucket
                            
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
                        try:
                            s3_client.delete_object(
                                Bucket=output_bucket,
                                Key=f"executions/{execution_id}/initiated"
                            )
                            logger.debug(f"Deleted 'initiated' marker after failed Lambda invocation")
                        except Exception as e:
                            logger.warning(f"Failed to delete initiated marker: {str(e)}")
                        
                        return {
                            'status': False,
                            'execution_id': execution_id,
                            'output_bucket': output_bucket,
                            'error': f"Lambda invocation failed with status code: {status_code}",
                            'output': f"Failed to invoke Lambda function {function_name} in region {lambda_region}"
                        }
                    
                except Exception as e:
                    logger.error(f"Lambda invocation failed with exception: {str(e)}")
                    
                    # Clean up initiated marker
                    try:
                        s3_client.delete_object(
                            Bucket=output_bucket,
                            Key=f"executions/{execution_id}/initiated"
                        )
                        logger.debug(f"Deleted 'initiated' marker after Lambda exception")
                    except Exception as se:
                        logger.warning(f"Failed to delete initiated marker: {str(se)}")
                    
                    return {
                        'status': False,
                        'execution_id': execution_id,
                        'output_bucket': output_bucket,
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
                        'value': execution_id
                    })
                
                # Add output_bucket if not present
                if not output_bucket_found:
                    env_vars.append({
                        'name': 'OUTPUT_BUCKET',
                        'value': output_bucket
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
                        try:
                            s3_client.delete_object(
                                Bucket=output_bucket,
                                Key=f"executions/{execution_id}/initiated"
                            )
                            logger.debug(f"Deleted 'initiated' marker after failed CodeBuild start")
                        except Exception as e:
                            logger.warning(f"Failed to delete initiated marker: {str(e)}")
                        
                        return {
                            'status': False,
                            'execution_id': execution_id,
                            'output_bucket': output_bucket,
                            'error': "Failed to start CodeBuild project",
                            'output': f"Failed to start CodeBuild project {project_name} in region {codebuild_region}"
                        }
                    
                    # Add build ID to payload
                    payload['build_id'] = build_id
                    
                    # Update initiated marker with build_id
                    try:
                        initiated_data['build_id'] = build_id
                        s3_client.put_object(
                            Bucket=output_bucket,
                            Key=f"executions/{execution_id}/initiated",
                            Body=json.dumps(initiated_data),
                            ContentType='application/json'
                        )
                    except Exception as e:
                        logger.warning(f"Failed to update initiated marker with build ID in S3: {str(e)}")
                        
                except Exception as e:
                    logger.error(f"CodeBuild start failed with exception: {str(e)}")
                    
                    # Clean up initiated marker
                    try:
                        s3_client.delete_object(
                            Bucket=output_bucket,
                            Key=f"executions/{execution_id}/initiated"
                        )
                        logger.debug(f"Deleted 'initiated' marker after CodeBuild exception")
                    except Exception as se:
                        logger.warning(f"Failed to delete initiated marker: {str(se)}")
                    
                    return {
                        'status': False,
                        'execution_id': execution_id,
                        'output_bucket': output_bucket,
                        'error': f"CodeBuild start failed with exception: {str(e)}",
                        'output': f"Exception when starting CodeBuild project {project_name} in region {codebuild_region}: {str(e)}"
                    }
                
            else:
                # Clean up initiated marker
                try:
                    s3_client.delete_object(
                        Bucket=output_bucket,
                        Key=f"executions/{execution_id}/initiated"
                    )
                    logger.debug(f"Deleted 'initiated' marker due to unsupported execution type")
                except Exception as e:
                    logger.warning(f"Failed to delete initiated marker: {str(e)}")
                
                raise ValueError(f"Unsupported execution_type: {execution_type}")
            
            # Prepare result with tracking information
            result = {
                'status': True,
                'execution_id': execution_id,
                'output_bucket': output_bucket,
                'execution_type': execution_type,
                'initiated_url': f"s3://{output_bucket}/executions/{execution_id}/initiated",
                'result_url': f"s3://{output_bucket}/executions/{execution_id}/result.json",
                'done_url': f"s3://{output_bucket}/executions/{execution_id}/done",
                'logs_url': f"s3://{output_bucket}/executions/{execution_id}/logs.txt",
                'build_expire_at': build_expire_at,
                'background': True,
                'output': f"Initiated {execution_type} execution with ID: {execution_id}"
            }
            
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
    
    def clear_execution(self, execution_id=None, output_bucket=None):
        """
        Clear all S3 objects related to a specific execution.
        
        Args:
            execution_id (str, optional): Execution ID to clear. If not provided,
                                         a deterministic ID will be generated.
            output_bucket (str, optional): S3 bucket where execution data is stored.
                                     
        Returns:
            int: Number of objects deleted, or -1 if an error occurred
        """
        if not execution_id:
            # Generate deterministic execution ID based on resource identifiers
            base_string = f"{self.resource_type}:{self.resource_id}"
            execution_id = hashlib.md5(base_string.encode()).hexdigest()
        
        # Determine output bucket using same priority order as in the decorator
        if not output_bucket:
            if hasattr(self, 'output_bucket') and self.output_bucket:
                output_bucket = self.output_bucket
            elif hasattr(self, 'tmp_bucket') and self.tmp_bucket:
                output_bucket = self.tmp_bucket
            elif os.environ.get('OUTPUT_BUCKET'):
                output_bucket = os.environ.get('OUTPUT_BUCKET')
            elif os.environ.get('TMP_BUCKET'):
                output_bucket = os.environ.get('TMP_BUCKET')
            else:
                raise ValueError("output_bucket must be provided as parameter or class attribute")
        
        logger = Config0Logger("AWSExecutor", logcategory="cloudprovider")
        
        try:
            # Delete entire execution directory from S3
            s3_client = boto3.client('s3')
            execution_prefix = f"executions/{execution_id}/"
            
            logger.info(f"Deleting execution directory for {execution_id}")
            
            # List all objects with the execution prefix
            paginator = s3_client.get_paginator('list_objects_v2')
            objects_to_delete = []
            
            # Collect all objects with the execution prefix
            for page in paginator.paginate(Bucket=output_bucket, Prefix=execution_prefix):
                if 'Contents' in page:
                    for obj in page['Contents']:
                        objects_to_delete.append({'Key': obj['Key']})
            
            # Delete all objects if any were found
            if objects_to_delete:
                s3_client.delete_objects(
                    Bucket=output_bucket,
                    Delete={'Objects': objects_to_delete}
                )
                logger.info(f"Deleted {len(objects_to_delete)} objects from execution directory")
                return len(objects_to_delete)
            else:
                logger.info(f"No existing objects found for execution {execution_id}")
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
                - clear_existing: Set to True to clear any existing execution files
                
                Or Lambdabuild invocation configuration:
                - FunctionName: Lambda function name
                - Payload: JSON payload or string with commands and environment variables
                
        Returns:
            dict: Execution tracking information with:
                - status: True if execution started successfully
                - execution_id: Unique identifier for the execution
                - output_bucket: S3 bucket for tracking
                - execution_type: "lambda"
                - initiated_url: URL to the initiated marker
                - result_url: URL to retrieve execution results
                - done_url: URL to the done marker
                - logs_url: URL to retrieve execution logs
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
                - clear_existing: Set to True to clear any existing execution files
                
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
                - initiated_url: URL to the initiated marker
                - result_url: URL to retrieve execution results
                - done_url: URL to the done marker
                - logs_url: URL to retrieve execution logs
        """
        pass  # Implementation handled by decorator
    
    def check_execution_status(self, execution_id=None, output_bucket=None):
        """
        Check the status of an execution.
        
        Args:
            execution_id (str, optional): Execution ID to check. If not provided,
                                         a deterministic ID will be generated.
            output_bucket (str, optional): S3 bucket where execution data is stored.
                                      Defaults to self.tmp_bucket.
                                      
        Returns:
            dict: Status information for the execution with the following structure:
                {
                    "execution_id": "<execution_id>",
                    "found": True/False,
                    "initiated": True/False,
                    "completed": True/False,
                    "success": True/False/None,
                    "initiated_time": <timestamp> or None,
                    "completed_time": <timestamp> or None,
                    "elapsed_time": <seconds> or None,
                    "result_url": "<s3_url>" or None,
                    "logs_url": "<s3_url>" or None
                }
        """
        if not execution_id:
            # Generate deterministic execution ID based on resource identifiers
            base_string = f"{self.resource_type}:{self.resource_id}"
            execution_id = hashlib.md5(base_string.encode()).hexdigest()
        
        # Determine output bucket using same priority order
        if not output_bucket:
            if hasattr(self, 'output_bucket') and self.output_bucket:
                output_bucket = self.output_bucket
            elif hasattr(self, 'tmp_bucket') and self.tmp_bucket:
                output_bucket = self.tmp_bucket
            elif os.environ.get('OUTPUT_BUCKET'):
                output_bucket = os.environ.get('OUTPUT_BUCKET')
            elif os.environ.get('TMP_BUCKET'):
                output_bucket = os.environ.get('TMP_BUCKET')
            else:
                raise ValueError("output_bucket must be provided as parameter or class attribute")
        
        logger = Config0Logger("AWSExecutor", logcategory="cloudprovider")
        
        # Initialize result structure
        result = {
            "execution_id": execution_id,
            "found": False,
            "initiated": False,
            "completed": False,
            "success": None,
            "initiated_time": None,
            "completed_time": None,
            "elapsed_time": None,
            "result_url": f"s3://{output_bucket}/executions/{execution_id}/result.json",
            "logs_url": f"s3://{output_bucket}/executions/{execution_id}/logs.txt"
        }
        
        try:
            s3_client = boto3.client('s3')
            
            # Check for initiated marker
            initiated_key = f"executions/{execution_id}/initiated"
            try:
                initiated_obj = s3_client.get_object(Bucket=output_bucket, Key=initiated_key)
                initiated_data = json.loads(initiated_obj['Body'].read().decode('utf-8'))
                
                result["found"] = True
                result["initiated"] = True
                result["initiated_time"] = initiated_data.get('start_time')
                
                # If execution has a build_id, include it
                if 'build_id' in initiated_data:
                    result["build_id"] = initiated_data['build_id']
                
                # Update result structure with additional initiated data
                for key in ['resource_type', 'resource_id', 'method', 'execution_type']:
                    if key in initiated_data:
                        result[key] = initiated_data[key]
                
            except s3_client.exceptions.NoSuchKey:
                logger.debug(f"No initiated marker found for execution {execution_id}")
            
            # Check for done marker
            done_key = f"executions/{execution_id}/done"
            try:
                done_obj = s3_client.get_object(Bucket=output_bucket, Key=done_key)
                done_data = done_obj['Body'].read().decode('utf-8')
                
                result["found"] = True
                result["completed"] = True
                
                # Try to parse the done marker as JSON if possible
                try:
                    done_json = json.loads(done_data)
                    
                    # If it's valid JSON, extract data
                    if isinstance(done_json, dict):
                        result["success"] = done_json.get('success', done_json.get('status'))
                        
                        if 'end_time' in done_json:
                            result["completed_time"] = done_json['end_time']
                        
                        # Copy any other fields from done_json to result
                        for key, value in done_json.items():
                            if key not in result:
                                result[key] = value
                except json.JSONDecodeError:
                    # If it's not JSON, use the raw content
                    result["success"] = done_data.strip().lower() in ['success', 'true']
                
                # Calculate elapsed time if we have both start and end times
                if result["initiated_time"] and result["completed_time"]:
                    result["elapsed_time"] = result["completed_time"] - result["initiated_time"]
                
            except s3_client.exceptions.NoSuchKey:
                logger.debug(f"No done marker found for execution {execution_id}")
            
            # If we found an initiated marker but no done marker, calculate elapsed time from now
            if result["initiated_time"] and not result["completed_time"]:
                result["elapsed_time"] = time.time() - result["initiated_time"]
                
            return result
            
        except Exception as e:
            logger.error(f"Error checking execution status: {str(e)}")
            result["error"] = str(e)
            return result
    
    def check_execution_timeout(self, execution_id=None, output_bucket=None, max_execution_time=None):
        """
        Check if an execution has timed out.
        
        Args:
            execution_id (str, optional): Execution ID to check.
            output_bucket (str, optional): S3 bucket for tracking.
            max_execution_time (int, optional): Maximum allowed execution time in seconds.
            
        Returns:
            dict: Result with timed_out flag and elapsed_time if available
        """
        if not execution_id:
            # Generate deterministic execution ID based on resource identifiers
            base_string = f"{self.resource_type}:{self.resource_id}"
            execution_id = hashlib.md5(base_string.encode()).hexdigest()
        
        # Determine output bucket using same priority order
        if not output_bucket:
            if hasattr(self, 'output_bucket') and self.output_bucket:
                output_bucket = self.output_bucket
            elif hasattr(self, 'tmp_bucket') and self.tmp_bucket:
                output_bucket = self.tmp_bucket
            elif os.environ.get('OUTPUT_BUCKET'):
                output_bucket = os.environ.get('OUTPUT_BUCKET')
            elif os.environ.get('TMP_BUCKET'):
                output_bucket = os.environ.get('TMP_BUCKET')
            else:
                raise ValueError("output_bucket must be provided as parameter or class attribute")
        
        # Determine max execution time
        max_execution_time = max_execution_time or getattr(self, 'max_execution_time', None)
        if not max_execution_time:
            # Try to get from build_env_vars
            build_env_vars = getattr(self, 'build_env_vars', {})
            if isinstance(build_env_vars, dict):
                if build_env_vars.get('BUILD_TIMEOUT'):
                    try:
                        max_execution_time = int(build_env_vars.get('BUILD_TIMEOUT'))
                    except (ValueError, TypeError):
                        pass
                
            # If still not found, try environment variables
            if not max_execution_time:
                if os.environ.get('BUILD_TIMEOUT'):
                    try:
                        max_execution_time = int(os.environ.get('BUILD_TIMEOUT'))
                    except (ValueError, TypeError):
                        pass
                
            # If still no timeout, use default based on resource type
            if not max_execution_time:
                resource_type = getattr(self, 'resource_type', '').lower()
                if resource_type == 'lambda':
                    max_execution_time = 900  # 15 minutes default for Lambda
                else:
                    max_execution_time = 3600  # 1 hour default for others
        
        logger = Config0Logger("AWSExecutor", logcategory="cloudprovider")
        
        # Check current status
        status = self.check_execution_status(execution_id, output_bucket)
        
        # If execution is completed, it didn't time out
        if status.get('completed'):
            return {"timed_out": False, "reason": "Execution is complete"}
        
        # If execution hasn't been initiated, it can't time out
        if not status.get('initiated'):
            return {"timed_out": False, "reason": "Execution not initiated"}
        
        # Check if execution has been running too long
        if status.get('initiated_time'):
            elapsed_time = time.time() - status['initiated_time']
            if elapsed_time > max_execution_time:
                logger.warning(f"Execution {execution_id} appears to have timed out after {elapsed_time:.2f} seconds")
                
                # Create a timeout done marker
                try:
                    s3_client = boto3.client('s3')
                    timeout_data = {
                        'success': False,
                        'status': 'failed',
                        'end_time': time.time(),
                        'error': f"Execution timed out after {elapsed_time:.2f} seconds"
                    }
                    s3_client.put_object(
                        Bucket=output_bucket,
                        Key=f"executions/{execution_id}/done",
                        Body=json.dumps(timeout_data),
                        ContentType='application/json'
                    )
                    logger.info(f"Created 'done' marker for timed out execution {execution_id}")
                except Exception as e:
                    logger.warning(f"Failed to create timeout done marker: {str(e)}")
                
                return {
                    "timed_out": True,
                    "elapsed_time": elapsed_time,
                    "execution_id": execution_id
                }
            else:
                return {
                    "timed_out": False,
                    "elapsed_time": elapsed_time,
                    "reason": "Execution is still within time limit"
                }
        
        return {"timed_out": False, "reason": "No initiated_time available in status"}
    
    def run_with_timeout(self, method=None, timeout=None, **kwargs):
        """
        Execute an operation with a specific timeout.
        
        This method clears any existing execution, starts a new one, and
        then waits for completion or timeout.
        
        Args:
            method (str, optional): Method to execute (create, destroy, etc.)
            timeout (int, optional): Maximum execution time in seconds
            **kwargs: Additional parameters to pass to the execution
            
        Returns:
            dict: Execution result including:
                - status: True if execution completed successfully
                - execution_id: Unique identifier for the execution
                - output_bucket: S3 bucket used for tracking
                - timed_out: True if execution timed out
                - elapsed_time: Time taken for execution
                - result: Result data if available
        """
        if method:
            kwargs['method'] = method
            
        # Set max_execution_time if timeout is specified
        if timeout:
            kwargs['max_execution_time'] = timeout
        
        # Get execution ID - either use provided one or generate a deterministic one
        execution_id = kwargs.get('execution_id')
        if not execution_id:
            base_string = f"{self.resource_type}:{self.resource_id}"
            execution_id = hashlib.md5(base_string.encode()).hexdigest()
        
        # Determine which bucket to use
        output_bucket = kwargs.get('output_bucket')
        if not output_bucket:
            if hasattr(self, 'output_bucket') and self.output_bucket:
                output_bucket = self.output_bucket
            elif hasattr(self, 'tmp_bucket') and self.tmp_bucket:
                output_bucket = self.tmp_bucket
            elif os.environ.get('OUTPUT_BUCKET'):
                output_bucket = os.environ.get('OUTPUT_BUCKET')
            elif os.environ.get('TMP_BUCKET'):
                output_bucket = os.environ.get('TMP_BUCKET')
        
        # Clear any existing execution
        self.clear_execution(execution_id, output_bucket)
        
        # Determine which execution method to use based on timeout
        build_timeout = kwargs.get('build_timeout') or getattr(self, 'build_timeout', None)
        
        # If timeout was specified for this call, use it
        if timeout:
            build_timeout = timeout
        
        try:
            build_timeout = int(build_timeout) if build_timeout else None
        except (ValueError, TypeError):
            build_timeout = None
        
        if not build_timeout:
            # Try to get from build_env_vars
            build_env_vars = kwargs.get('build_env_vars') or getattr(self, 'build_env_vars', {})
            if isinstance(build_env_vars, dict):
                if build_env_vars.get('BUILD_TIMEOUT'):
                    try:
                        build_timeout = int(build_env_vars.get('BUILD_TIMEOUT'))
                    except (ValueError, TypeError):
                        pass
        
        # Set clear_existing to True to ensure we clear any previous execution
        kwargs['clear_existing'] = True
        
        # Use CodeBuild for longer operations
        if build_timeout and build_timeout > 800:
            exec_result = self.exec_codebuild(**kwargs)
        else:
            exec_result = self.exec_lambda(**kwargs)
        
        # If execution failed to start, return the result
        if not exec_result.get('status'):
            return exec_result
        
        # Return the initial execution result
        return exec_result