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
                
                if not max_execution_time and build_env_vars.get('TIMEOUT'):
                    try:
                        max_execution_time = int(build_env_vars.get('TIMEOUT'))
                        logger.debug(f"Using timeout from build_env_vars TIMEOUT: {max_execution_time}s")
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
                
                if not max_execution_time and os.environ.get('TIMEOUT'):
                    try:
                        max_execution_time = int(os.environ.get('TIMEOUT'))
                        logger.debug(f"Using timeout from env TIMEOUT: {max_execution_time}s")
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
            
            # Add buffer time for execution tracking (to account for overheads)
            tracking_max_time = max_execution_time + 300  # Add 5 minutes buffer

            # Generate a deterministic execution ID based on resource identifiers
            # This allows checking for existing executions
            if kwargs.get('execution_id'):
                # Use provided execution_id if available
                execution_id = kwargs.get('execution_id')
                logger.debug(f"Using provided execution_id: {execution_id}")
            else:
                # Create a deterministic execution ID based on resource identifiers and timestamp
                base_string = f"{resource_type}:{resource_id}:{method}"

                if kwargs.get('force_new_execution') or getattr(self, 'force_new_execution', False) or os.environ.get('FORCE_NEW_EXECUTION'):
                    # Add timestamp to force a new execution
                    base_string = f"{base_string}:{time.time()}"
                    logger.debug(f"Forcing new execution with unique base string: {base_string}")

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
            
            # Check if execution is already in progress
            if not kwargs.get('force_new_execution') and not getattr(self, 'force_new_execution', False) and not os.environ.get('FORCE_NEW_EXECUTION'):
                try:
                    # Check if status file exists in S3
                    s3_client = boto3.client('s3')
                    status_key = f"executions/{execution_id}/status"

                    try:
                        status_obj = s3_client.get_object(Bucket=output_bucket, Key=status_key)
                        status_data = json.loads(status_obj['Body'].read().decode('utf-8'))

                        # If status indicates execution is in progress, check if it might have timed out
                        if status_data.get('status') == 'in_progress':
                            # Check if execution has been running too long (timed out)
                            if 'start_time' in status_data:
                                elapsed_time = time.time() - status_data['start_time']
                                if elapsed_time > tracking_max_time:
                                    logger.warning(f"Execution {execution_id} appears to have timed out after {elapsed_time:.2f} seconds")
                                    
                                    # Update status to timed_out
                                    status_data['status'] = 'timed_out'
                                    status_data['end_time'] = time.time()
                                    status_data['error'] = f"Execution timed out after {elapsed_time:.2f} seconds"
                                    
                                    try:
                                        s3_client.put_object(
                                            Bucket=output_bucket,
                                            Key=status_key,
                                            Body=json.dumps(status_data),
                                            ContentType='application/json'
                                        )
                                        logger.info(f"Updated status of timed out execution {execution_id}")
                                    except Exception as e:
                                        logger.warning(f"Failed to update timed out status: {str(e)}")
                                        
                                    # If we detected a timeout, continue with new execution
                                    if not kwargs.get('abort_on_timeout', False):
                                        logger.info(f"Starting new execution after timeout")
                                    else:
                                        # Return the timed out status if abort_on_timeout is set
                                        return {
                                            'status': False,
                                            'execution_id': execution_id,
                                            'output_bucket': output_bucket,
                                            'execution_type': execution_type,
                                            'error': f"Previous execution timed out after {elapsed_time:.2f} seconds",
                                            'output': f"Execution {execution_id} timed out and abort_on_timeout is set"
                                        }
                                else:
                                    # Execution is still within timeout window
                                    remaining_time = tracking_max_time - elapsed_time
                                    logger.info(f"Execution already in progress for {resource_type}:{resource_id} with ID {execution_id}")
                                    logger.info(f"Elapsed time: {elapsed_time:.2f}s, Estimated remaining time: {remaining_time:.2f}s")
                                    
                                    return {
                                        'status': True,
                                        'execution_id': execution_id,
                                        'output_bucket': output_bucket,
                                        'execution_type': execution_type,
                                        'status_url': f"s3://{output_bucket}/executions/{execution_id}/status",
                                        'result_url': f"s3://{output_bucket}/executions/{execution_id}/result.json",
                                        'logs_url': f"s3://{output_bucket}/executions/{execution_id}/logs.txt",
                                        'output': f"Execution already in progress with ID: {execution_id}",
                                        'already_running': True,
                                        'elapsed_time': elapsed_time,
                                        'remaining_time': remaining_time
                                    }
                            else:
                                # No start_time in status data
                                logger.info(f"Execution already in progress for {resource_type}:{resource_id} with ID {execution_id}")
                                return {
                                    'status': True,
                                    'execution_id': execution_id,
                                    'output_bucket': output_bucket,
                                    'execution_type': execution_type,
                                    'status_url': f"s3://{output_bucket}/executions/{execution_id}/status",
                                    'result_url': f"s3://{output_bucket}/executions/{execution_id}/result.json",
                                    'logs_url': f"s3://{output_bucket}/executions/{execution_id}/logs.txt",
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
                'output_bucket': output_bucket,
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
                    'execution_type': execution_type,
                    'max_execution_time': max_execution_time,
                    'tracking_max_time': tracking_max_time
                }
                s3_client.put_object(
                    Bucket=output_bucket,
                    Key=f"executions/{execution_id}/status",
                    Body=json.dumps(status_data),
                    ContentType='application/json'
                )
            except Exception as e:
                logger.warning(f"Failed to write initial status to S3: {str(e)}")
                # Continue even if status write fails
            
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
                        
                        # Update status in S3
                        try:
                            status_data['status'] = 'failed'
                            status_data['end_time'] = time.time()
                            status_data['error'] = f"Lambda invocation failed with status code: {status_code}"
                            s3_client.put_object(
                                Bucket=output_bucket,
                                Key=f"executions/{execution_id}/status",
                                Body=json.dumps(status_data),
                                ContentType='application/json'
                            )
                        except Exception as e:
                            logger.warning(f"Failed to update status in S3: {str(e)}")
                        
                        return {
                            'status': False,
                            'execution_id': execution_id,
                            'output_bucket': output_bucket,
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
                            Bucket=output_bucket,
                            Key=f"executions/{execution_id}/status",
                            Body=json.dumps(status_data),
                            ContentType='application/json'
                        )
                    except Exception as se:
                        logger.warning(f"Failed to update status in S3: {str(se)}")
                    
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
                        
                        # Update status in S3
                        try:
                            status_data['status'] = 'failed'
                            status_data['end_time'] = time.time()
                            status_data['error'] = "Failed to start CodeBuild project"
                            s3_client.put_object(
                                Bucket=output_bucket,
                                Key=f"executions/{execution_id}/status",
                                Body=json.dumps(status_data),
                                ContentType='application/json'
                            )
                        except Exception as e:
                            logger.warning(f"Failed to update status in S3: {str(e)}")
                        
                        return {
                            'status': False,
                            'execution_id': execution_id,
                            'output_bucket': output_bucket,
                            'error': "Failed to start CodeBuild project",
                            'output': f"Failed to start CodeBuild project {project_name} in region {codebuild_region}"
                        }
                    
                    # Add build ID to response
                    payload['build_id'] = build_id
                    status_data['build_id'] = build_id
                    
                    # Update status with build ID
                    try:
                        s3_client.put_object(
                            Bucket=output_bucket,
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
                            Bucket=output_bucket,
                            Key=f"executions/{execution_id}/status",
                            Body=json.dumps(status_data),
                            ContentType='application/json'
                        )
                    except Exception as se:
                        logger.warning(f"Failed to update status in S3: {str(se)}")
                    
                    return {
                        'status': False,
                        'execution_id': execution_id,
                        'output_bucket': output_bucket,
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
                        Bucket=output_bucket,
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
                'output_bucket': output_bucket,
                'execution_type': execution_type,
                'status_url': f"s3://{output_bucket}/executions/{execution_id}/status",
                'result_url': f"s3://{output_bucket}/executions/{execution_id}/result.json",
                'logs_url': f"s3://{output_bucket}/executions/{execution_id}/logs.txt",
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
                - force_new_execution: Force a new execution regardless of existing ones
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
        
        This method can handle both direct parameters and a pre-configured invocation
        configuration from Lambdabuild.
        
        Args:
            **kwargs: Operation parameters including:
                - method: Operation method (create, destroy, etc.)
                - build_env_vars: Environment variables for the build
                - ssm_name: SSM parameter name (if applicable)
                - force_new_execution: Force a new execution regardless of existing ones
                
                Or Lambdabuild invocation configuration:
                - FunctionName: Lambda function name
                - Payload: JSON payload or string with commands and environment variables
                
        Returns:
            dict: Execution tracking information with:
                - status: True if execution started successfully
                - execution_id: Unique identifier for the execution
                - output_bucket: S3 bucket for tracking
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
        
        This method can handle both direct parameters and a pre-configured build
        specification from Codebuild.
        
        Args:
            **kwargs: Operation parameters including:
                - method: Operation method (create, destroy, etc.)
                - build_env_vars: Environment variables for the build
                - ssm_name: SSM parameter name (if applicable)
                - force_new_execution: Force a new execution regardless of existing ones
                
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
                - status_url: URL to check execution status
                - result_url: URL to retrieve execution results
                - logs_url: URL to retrieve execution logs
        """
        pass  # Implementation handled by decorator
    
    def get_execution_status(self, execution_id=None, output_bucket=None):
        """
        Get the status of an execution.
        
        Args:
            execution_id (str, optional): Execution ID to check. If not provided,
                                         a deterministic ID will be generated.
            output_bucket (str, optional): S3 bucket where execution data is stored.
                                      Defaults to self.tmp_bucket.
                                      
        Returns:
            dict: Status information for the execution, or None if not found
        """
        if not execution_id:
            # Generate deterministic execution ID based on resource identifiers
            base_string = f"{self.resource_type}:{self.resource_id}:{getattr(self, 'method', 'unknown')}"
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
        
        try:
            s3_client = boto3.client('s3')
            status_key = f"executions/{execution_id}/status"
            
            try:
                status_obj = s3_client.get_object(Bucket=output_bucket, Key=status_key)
                status_data = json.loads(status_obj['Body'].read().decode('utf-8'))
                return status_data
            except s3_client.exceptions.NoSuchKey:
                logger.debug(f"No status found for execution {execution_id}")
                return None
        except Exception as e:
            logger.error(f"Error retrieving execution status: {str(e)}")
            return None
    
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
            base_string = f"{self.resource_type}:{self.resource_id}:{getattr(self, 'method', 'unknown')}"
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
                
                if not max_execution_time and build_env_vars.get('TIMEOUT'):
                    try:
                        max_execution_time = int(build_env_vars.get('TIMEOUT'))
                    except (ValueError, TypeError):
                        pass
            
            # If still not found, try environment variables
            if not max_execution_time:
                if os.environ.get('BUILD_TIMEOUT'):
                    try:
                        max_execution_time = int(os.environ.get('BUILD_TIMEOUT'))
                    except (ValueError, TypeError):
                        pass
                
                if not max_execution_time and os.environ.get('TIMEOUT'):
                    try:
                        max_execution_time = int(os.environ.get('TIMEOUT'))
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
        
        # Check status in S3
        status_data = self.get_execution_status(execution_id, output_bucket)
        if not status_data:
            return {"timed_out": False, "reason": "No execution found"}
        
        # If status is already set to something other than in_progress, it's not running
        if status_data.get('status') != 'in_progress':
            return {
                "timed_out": False, 
                "reason": f"Execution is not in progress (status: {status_data.get('status')})"
            }
        
        # Check if execution has been running too long
        if 'start_time' in status_data:
            elapsed_time = time.time() - status_data['start_time']
            if elapsed_time > max_execution_time:
                # Update status to timed_out
                try:
                    status_data['status'] = 'timed_out'
                    status_data['end_time'] = time.time()
                    status_data['error'] = f"Execution timed out after {elapsed_time:.2f} seconds"
                    
                    s3_client = boto3.client('s3')
                    s3_client.put_object(
                        Bucket=output_bucket,
                        Key=f"executions/{execution_id}/status",
                        Body=json.dumps(status_data),
                        ContentType='application/json'
                    )
                    logger.info(f"Updated status of timed out execution {execution_id}")
                except Exception as e:
                    logger.warning(f"Failed to update timed out status: {str(e)}")
                
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
        
        return {"timed_out": False, "reason": "No start_time available in status"}
    
    def force_execution(self, method=None, **kwargs):
        """
        Force a new execution regardless of any existing executions.
        
        This is useful for retrying failed or stuck executions.
        
        Args:
            method (str, optional): Method to execute (create, destroy, etc.)
            **kwargs: Additional parameters to pass to the execution
            
        Returns:
            dict: Execution tracking information
        """
        if method:
            kwargs['method'] = method
        
        kwargs['force_new_execution'] = True
        
        # Determine whether to use Lambda or CodeBuild based on timeout
        build_timeout = kwargs.get('build_timeout') or getattr(self, 'build_timeout', None)
        
        try:
            build_timeout = int(build_timeout) if build_timeout else None
        except (ValueError, TypeError):
            build_timeout = None
        
        if not build_timeout:
            # Try to get timeout from build_env_vars
            build_env_vars = kwargs.get('build_env_vars') or getattr(self, 'build_env_vars', {})
            if isinstance(build_env_vars, dict):
                if build_env_vars.get('BUILD_TIMEOUT'):
                    try:
                        build_timeout = int(build_env_vars.get('BUILD_TIMEOUT'))
                    except (ValueError, TypeError):
                        pass
                
                if not build_timeout and build_env_vars.get('TIMEOUT'):
                    try:
                        build_timeout = int(build_env_vars.get('TIMEOUT'))
                    except (ValueError, TypeError):
                        pass
        
        # If still not found, try environment variables
        if not build_timeout:
            if os.environ.get('BUILD_TIMEOUT'):
                try:
                    build_timeout = int(os.environ.get('BUILD_TIMEOUT'))
                except (ValueError, TypeError):
                    pass
            
            if not build_timeout and os.environ.get('TIMEOUT'):
                try:
                    build_timeout = int(os.environ.get('TIMEOUT'))
                except (ValueError, TypeError):
                    pass
        
        # Use CodeBuild for longer operations
        if build_timeout and build_timeout > 800:
            return self.exec_codebuild(**kwargs)
        else:
            return self.exec_lambda(**kwargs)