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
    - Plain text (text/plain): Integer if valid, float if valid, otherwise string.
    - Other content types: Raw bytes.
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content_type = response.get('ContentType', '')
        content = response['Body'].read()

        if content_type == 'application/json':
            return json.loads(content.decode('utf-8'))  # Parse JSON
        
        if content_type in ['text/plain', 'application/octet-stream']:
            decoded = content.decode('utf-8').strip()
            
            # First, check if it's a valid float
            try:
                value = float(decoded)
                # If it's a float, return as int if no decimal part, otherwise as float
                return int(value) if value.is_integer() else value
            except ValueError:
                # If not a float, return as a plain string
                return decoded
        
        # For other content types, return raw bytes
        return content
    
    except Exception as e:
        print(f'    ----- _s3_get_object s3://{bucket}/{key}')
        print(f"    ----- Error fetching object: {e}")
        return False

def _set_build_status_codes(build_status):

    if build_status == "SUCCEEDED":
        return {
            "status_code": "successful",
            "status": True,
        }

    failed_message = f"codebuild failed with build status {build_status}"

    FAILED_STATUSES = {
        "FAILED",
        "FAULT",
        "STOPPED",
        "FAILED_WITH_ABORT",
    }

    if build_status in FAILED_STATUSES:
        return {
            "failed_message": failed_message,
            "status_code": "failed",
            "status": False,
        }

    if build_status == "TIMED_OUT":
        return {
            "failed_message": failed_message,
            "status_code": "timed_out",
            "status": False,
        }

    return {
        "status": None,
    }

def _eval_build_status(status_data,clobber=False):

    build_id = status_data["build_id"]

    # Get actual CodeBuild build status from API
    codebuild_client = boto3.client('codebuild',
                                    region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

    build_data = codebuild_client.batch_get_builds(ids=[build_id])['builds'][0]
    build_status = build_data.get('buildStatus')
    print(f"   ---- build status for build_id {build_id}: {build_status} -------")
    print(f"   ---- build status for build_id {build_id}: {build_status} -------")
    print(f"   ---- build status for build_id {build_id}: {build_status} -------")
    print(f"   ---- build status for build_id {build_id}: {build_status} -------")
    print(f"   ---- build status for build_id {build_id}: {build_status} -------")
    print(f"   ---- build status for build_id {build_id}: {build_status} -------")
    print(f"   ---- build status for build_id {build_id}: {build_status} -------")
    raise

    status = None

    if build_status == "IN_PROGRESS":
        status = "in_progress"
        return status

    for retry in range(30):
        build_status_results = _set_build_status_codes(build_status)
        if build_status_results["status"] is None:
            time.sleep(10)
        status = True
        break

    if build_status_results["status"] is not None and clobber:
        status_data['build_status'] = build_status_results['status_code']
        status_data['status'] = build_status_results['status']
        status = False

    return status

def get_execution_status(execution_type, execution_id=None, output_bucket=None):
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
    result["t0"] = int(_s3_get_object(s3_client, output_bucket, initiated_key))
    if result.get("t0"):
        result["initiated"] = True
    else:
        del result["t0"]

    if not result.get("initiated"):
        return result

    expire_at_key = f"executions/{execution_id}/expire_at"
    expire_at = int(_s3_get_object(s3_client, output_bucket, expire_at_key))
    if int(time.time()) > expire_at:
        result["expired"] = True

    if result.get("expired"):
        return result

    status_key = f"executions/{execution_id}/status.json"
    result["status"] = _s3_get_object(s3_client, output_bucket, status_key)
    if not result.get("status"):
        del result["status"]

    # Check for done marker
    done_key = f"executions/{execution_id}/done"
    result["t1"] = int(_s3_get_object(s3_client, output_bucket, done_key))
    if result.get("t1"):
        result["done"] = True
    else:
        del result["t1"]

    result_key = f"executions/{execution_id}/result.json"

    results = _s3_get_object(s3_client,
                             output_bucket,
                             result_key)

    # only lambda will have this result.json
    if result.get("done") and execution_type == "lambda":
        result["results"] = results
        return result

    # For CodeBuild, check actual build status even if done is not written
    if execution_type == "codebuild":
        status_data = result["status"]
        build_status = _eval_build_status(status_data,clobber=False)
        if result.get("done") or build_status in [True, False]:
            if result.get("done"):
                print("     ----- execution is done")
            elif build_status in [True,False]:
                print("     ----- build_status is True/False")
                time.sleep(15)  # wait until codebuild is fully stopped
            # Write updated status.json back to S3
            if _eval_build_status(status_data,clobber=True) in [True,False]:
                _s3_put_object(
                    s3_client,
                    output_bucket,
                    status_key,
                    json.dumps(status_data),
                    content_type='application/json'
                )
                result["status"] = status_data

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

            init = None

            # Store original args
            original_args = kwargs.copy()

            s3_client = boto3.client('s3')

            # Initialize logger
            logger = Config0Logger("AWSExecutor", logcategory="cloudprovider")
            logger.debug(f"Starting {execution_type} execution with {func.__name__} within decorator")

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
                if execution_type == "lambda":
                    max_execution_time = 900  # 15 minutes default for Lambda
                    logger.debug(f"Using default Lambda timeout: {max_execution_time}s")
                else:  # codebuild or anything else
                    max_execution_time = 3600  # 1 hour default for CodeBuild
                    logger.debug(f"Using default CodeBuild timeout: {max_execution_time}s")
            
            # Calculate build expiration time
            build_expire_at = int(time.time()) + int(max_execution_time)
            existing_run = self.check_execution_status(execution_type)

            # ref 5634623
            if existing_run.get("done"):
                logger.debug("existing run is done, clearing execution")
                self.clear_execution()
                if "results" in existing_run:
                    return existing_run["results"]
                return existing_run

            if existing_run.get("status") is False and execution_type == "codebuild":
                logger.debug("existing codebuild is False")
                self.clear_execution()
                return existing_run

            if existing_run.get("status"):
                logger.debug("existing run in progress, returning status")
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
            s3_client.put_object(Bucket=self.output_bucket, Key=f"executions/{self.execution_id}/initiated", Body=str(int(time.time())))
            logger.debug(f"initiated execution {self.execution_id}/initiated in bucket {self.output_bucket}")
            init = True

            # Execute based on type
            if execution_type == "lambda":
                # Get Lambda function details - only use FunctionName from invocation_config
                function_name = kwargs.get('FunctionName') or getattr(self, 'lambda_function_name', 'config0-iac')
                lambda_region = getattr(self, 'lambda_region', 'us-east-1')
                logger.debug(f"Invoking Lambda function {function_name} in region {lambda_region}")
                
                # Check if this is a pre-configured payload from Lambdabuild
                if kwargs.get('Payload'):
                    # If it's a string, assume it's already JSON formatted
                    if isinstance(kwargs['Payload'], str):
                        try:
                            payload_obj = json.loads(kwargs['Payload'])
                        except:
                            payload_obj = {}
                        # Ensure payload is a dict
                        if not isinstance(payload_obj, dict):
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

                try:
                    # Initialize Lambda client with specific region for Lambda
                    lambda_client = boto3.client('lambda', region_name=lambda_region)
                    response = lambda_client.invoke(**lambda_params)
                    status_code = response.get('StatusCode')
                    logger.debug(f"Lambda invocated with {lambda_params} status code: {status_code}")

                    # For Event invocation type, 202 Accepted is expected
                    if status_code != 202:
                        logger.error(f'Lambda invocation failed with with lambda_params: {lambda_params} and status code: {status_code}')
                        self.clear_execution()
                        return {
                            'init': init,
                            'status': False,
                            'execution_id': self.execution_id,
                            'output_bucket': self.output_bucket,
                            'error': f"Lambda invocation failed with status code: {status_code}",
                            'output': f"Failed to invoke Lambda function {function_name} in region {lambda_region}"
                        }

                except Exception as e:
                    logger.error(
                        f'Lambda invocation failed with with lambda_params: {lambda_params} with exception: {str(e)}')
                    self.clear_execution()
                    return {
                        'status': False,
                        'execution_id': self.execution_id,
                        'output_bucket': self.output_bucket,
                        'error': f"Lambda invocation failed with exception: {str(e)}",
                        'output': f"Exception when invoking Lambda function {function_name} in region {lambda_region}: {str(e)}"
                    }
                    
            elif execution_type == "codebuild":
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
                            'init': init,
                            'status': False,
                            'execution_id': self.execution_id,
                            'output_bucket': self.output_bucket,
                            'error': "Failed to start CodeBuild project",
                            'output': f"Failed to start CodeBuild project {project_name} in region {codebuild_region}"
                        }
                    
                    # Add build ID to payload
                    payload['build_id'] = build_id
                    s3_client.put_object(Bucket=self.output_bucket, Key=f"executions/{self.execution_id}/initiated", Body=str(int(time.time())))
                    init = True

                except Exception as e:
                    logger.error(f"CodeBuild start failed with exception: {str(e)}")
                    self.clear_execution()
                    return {
                        'init': init,
                        'status': False,
                        'execution_id': self.execution_id,
                        'output_bucket': self.output_bucket,
                        'error': f"CodeBuild start failed with exception: {str(e)}",
                        'output': f"Exception when starting CodeBuild project {project_name} in region {codebuild_region}: {str(e)}"
                    }
                
            else:
                self.clear_execution()
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

            # Add build ID for CodeBuild if available
            if execution_type == "codebuild" and 'build_id' in locals():
                result['build_id'] = build_id

            _s3_put_object(s3_client,
                           self.output_bucket,
                           f"executions/{self.execution_id}/status.json",
                           json.dumps(result),
                           content_type='application/json')

            _s3_put_object(s3_client,
                           self.output_bucket,
                           f"executions/{self.execution_id}/expire_at",
                           str(build_expire_at))

            # Record this invocation if we have the tracking method
            if hasattr(self, '_record_invocation'):
                try:
                    # This is an initial invocation, not a followup
                    self._record_invocation(f'{execution_type}_async', False, original_args, result)
                    result["init"] = init
                except Exception as e:
                    logger.warning(f"Failed to record invocation: {str(e)}")
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
        output_bucket (str): S3 bucket for storing execution results
        execution_id (str): Deterministic or provided execution ID
    """
    
    # Class-level defaults
    lambda_function_name = os.environ.get("LAMBDA_FUNCTION_NAME", "config0-iac")
    lambda_region = os.environ.get("LAMBDA_REGION", "us-east-1")  # Default to us-east-1 for Lambda
    codebuild_project_name = os.environ.get("CODEBUILD_PROJECT_NAME", "config0-iac")
    
    # Maximum number of invocations to track per execution
    MAX_INVOCATION_HISTORY = 3

    def __init__(self, resource_type, resource_id, execution_id, output_bucket, **kwargs):
        """
        Initialize a new AWS Async Executor.

        Args:
            resource_type (str): Type of infrastructure resource (terraform, cloudformation, etc.)
            resource_id (str): Identifier for the specific resource
            execution_id (str, optional): Execution ID for tracking. Can be used in both sync and async modes.
            output_bucket (str, optional): S3 bucket for execution tracking.
            async_mode (bool, optional): Explicitly set async mode. If None, defaults to execution_id being None.
            **kwargs: Additional attributes to configure the execution environment
        """
        self.logger = Config0Logger("AWSAsyncExecutor", logcategory="cloudprovider")

        # Validate input types
        if not isinstance(resource_type, str):
            raise TypeError(f"resource_type must be a string, got {type(resource_type).__name__}")
        if not isinstance(resource_id, str):
            raise TypeError(f"resource_id must be a string, got {type(resource_id).__name__}")
        if execution_id is not None and not isinstance(execution_id, str):
            raise TypeError(f"execution_id must be a string or None, got {type(execution_id).__name__}")
        if output_bucket is not None and not isinstance(output_bucket, str):
            raise TypeError(f"output_bucket must be a string or None, got {type(output_bucket).__name__}")

        # Assign attributes
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.execution_id = execution_id
        self.output_bucket = output_bucket

        # Set tmp_bucket for backward compatibility
        self.tmp_bucket = output_bucket


    def _record_invocation(self, invocation_type, is_followup, args, result, done=False):
        """
        Record an invocation to S3
        
        Args:
            invocation_type (str): Type of invocation (lambda, codebuild)
            is_followup (bool): Whether this is a follow-up status check
            args (dict): Arguments passed to the execution method
            result (dict): Result returned from the execution

        Returns:
            bool: True if recording was successful, False otherwise
        """
        # If we don't have S3 storage, skip recording
        if not self.output_bucket:
            return False
            
        # Create a record ID that allows tracking across processes
        record_id = str(uuid.uuid4())
        
        # Create a timestamped record
        record = {
            'record_id': record_id,
            'timestamp': int(time.time()),
            'checkin': int(time.time()),
            'invocation_type': invocation_type,
            'is_followup': is_followup,
            'arguments': args.copy() if args else {},  # Make a copy to avoid reference issues
            'result': result
        }

        if done:
            record["done"] = True
        
        # Get the correct execution ID - either from self or from args
        execution_id = self.execution_id
        if not execution_id and 'execution_id' in args:
            execution_id = args['execution_id']
            
        # Skip recording if we don't have an execution ID
        if not execution_id:
            return False
            
        try:
            # Always write the individual invocation record
            s3_client = boto3.client('s3')
            invocation_key = f"executions/invocations/{execution_id}/invocations/{record_id}.json"
            
            _s3_put_object(s3_client,
                          self.output_bucket,
                          invocation_key,
                          json.dumps(record),
                          content_type='application/json')
            
            # Now update the summary history with limited entries
            try:
                # Try to read existing summary history
                history_key = f"executions/invocations/{execution_id}/invocation_history.json"
                history = _s3_get_object(s3_client, self.output_bucket, history_key)
                
                if isinstance(history, dict) and 'invocations' in history:
                    # Add new record to list
                    invocations = history['invocations']
                    invocations.append(record)
                    
                    # Keep only the most recent MAX_INVOCATION_HISTORY items
                    if len(invocations) > self.MAX_INVOCATION_HISTORY:
                        invocations = invocations[-self.MAX_INVOCATION_HISTORY:]
                    
                    # Update history object
                    history['invocations'] = invocations
                    
                    # Write updated history
                    _s3_put_object(s3_client,
                                  self.output_bucket,
                                  history_key,
                                  json.dumps(history),
                                  content_type='application/json')
                else:
                    # Create new history object
                    new_history = {
                        'execution_id': execution_id,
                        'invocations': [record]
                    }
                    
                    # Write new history
                    _s3_put_object(s3_client,
                                  self.output_bucket,
                                  history_key,
                                  json.dumps(new_history),
                                  content_type='application/json')
            except:
                # If reading/updating summary fails, create a new one
                new_history = {
                    'execution_id': execution_id,
                    'invocations': [record]
                }
                
                _s3_put_object(s3_client,
                              self.output_bucket,
                              history_key,
                              json.dumps(new_history),
                              content_type='application/json')
                
            return True
                
        except Exception as e:
            print(f"Failed to record invocation to S3: {str(e)}")
            return False

    def _direct_lambda_execution(self, **kwargs):
        """
        Directly execute Lambda function in synchronous mode (no async tracking)
        """
        # Store original args for history
        original_args = kwargs.copy()
        
        self.logger.debug("Executing Lambda function in synchronous mode")
        
        # Get Lambda function details
        function_name = kwargs.get('FunctionName') or getattr(self, 'lambda_function_name', 'config0-iac')
        lambda_region = getattr(self, 'lambda_region', 'us-east-1')
        
        # Initialize Lambda client
        lambda_client = boto3.client('lambda', region_name=lambda_region)
        
        # Prepare the payload
        payload = {
            'params': kwargs,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id
        }
        
        # Add additional attributes if available
        for attr in ['stateful_id', 'method', 'aws_region', 'version', 
                     'binary', 'build_timeout', 'app_dir', 'app_name', 
                     'remote_stateful_bucket']:
            if hasattr(self, attr):
                payload[attr] = getattr(self, attr)
        
        # If there's a pre-configured payload, merge with it
        if kwargs.get('Payload'):
            if isinstance(kwargs['Payload'], str):
                try:
                    payload_obj = json.loads(kwargs['Payload'])
                    if isinstance(payload_obj, dict):
                        # Merge the payloads
                        for key, value in payload.items():
                            if key not in payload_obj:
                                payload_obj[key] = value
                        payload = payload_obj
                except:
                    pass
            elif isinstance(kwargs['Payload'], dict):
                # Merge the payloads
                for key, value in payload.items():
                    if key not in kwargs['Payload']:
                        kwargs['Payload'][key] = value
                payload = kwargs['Payload']
        
        lambda_payload = json.dumps(payload)
        
        # Prepare Lambda invocation parameters
        lambda_params = {
            'FunctionName': function_name,
            'InvocationType': 'RequestResponse',  # Synchronous
            'Payload': lambda_payload
        }
        
        try:
            # Invoke Lambda function
            response = lambda_client.invoke(**lambda_params)
            
            # Check response status
            status_code = response.get('StatusCode')

            if status_code != 200:
                self.logger.error(f"Lambda invocation failed with status code: {status_code}")
                self.clear_execution()
                result = {
                    'status': False,
                    'error': f"Lambda invocation failed with status code: {status_code}",
                    'output': f"Failed to invoke Lambda function {function_name} in region {lambda_region}"
                }
                # Record the execution in history - not a followup
                self._record_invocation('lambda_direct', False, original_args, result)
                return result
            
            # Get the response payload
            response_payload = response.get('Payload').read().decode('utf-8')
            
            try:
                # Parse the response
                result = json.loads(response_payload)
                # Record the execution in history - not a followup
                self._record_invocation('lambda_direct', False, original_args, result)
                return result
            except:
                # If parsing fails, return the raw response
                result = {
                    'status': True,
                    'output': response_payload
                }
                # Record the execution in history - not a followup
                self._record_invocation('lambda_direct', False, original_args, result)
                return result
                
        except Exception as e:
            self.logger.error(f"Lambda invocation failed with exception: {str(e)}")
            self.clear_execution()
            result = {
                'status': False,
                'error': f"Lambda invocation failed with exception: {str(e)}",
                'output': f"Exception when invoking Lambda function {function_name} in region {lambda_region}: {str(e)}"
            }
            # Record the execution in history - not a followup
            self._record_invocation('lambda_direct', False, original_args, result)
            return result

    def _direct_codebuild_execution(self, **kwargs):
        """
        Start a CodeBuild project and wait for completion (sync mode)
        """
        # Store original args for history
        original_args = kwargs.copy()
        
        self.logger.debug("Starting CodeBuild project in synchronous mode")
        
        # Start with all the original parameters
        build_params = dict(kwargs)
        
        # Get the project name
        project_name = build_params.get('projectName') or getattr(self, 'codebuild_project_name', 'config0-iac')
        build_params['projectName'] = project_name
        
        # Handle environment variables
        if 'environmentVariablesOverride' in build_params:
            env_vars = build_params['environmentVariablesOverride']
        else:
            env_vars = []
            build_params['environmentVariablesOverride'] = env_vars
        
        # Add our resource information to environment variables
        resource_vars = [
            {'name': 'RESOURCE_TYPE', 'value': self.resource_type},
            {'name': 'RESOURCE_ID', 'value': self.resource_id}
        ]
        
        for var in resource_vars:
            found = False
            for env_var in env_vars:
                if env_var.get('name') == var['name']:
                    found = True
                    break
            if not found:
                env_vars.append(var)
        
        # Add other attributes as environment variables
        for attr in ['stateful_id', 'method', 'aws_region', 'app_dir', 'app_name']:
            if hasattr(self, attr):
                found = False
                for env_var in env_vars:
                    if env_var.get('name') == attr.upper():
                        found = True
                        break
                if not found and getattr(self, attr):
                    env_vars.append({
                        'name': attr.upper(),
                        'value': str(getattr(self, attr))
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
        
        # Initialize CodeBuild client
        codebuild_client = boto3.client('codebuild', region_name=codebuild_region)
        
        try:
            # Start the build
            response = codebuild_client.start_build(**build_params)
            
            # Extract build information
            build = response.get('build', {})
            build_id = build.get('id')
            
            if not build_id:
                self.logger.error("Failed to start CodeBuild project")
                result = {
                    'status': False,
                    'error': "Failed to start CodeBuild project",
                    'output': f"Failed to start CodeBuild project {project_name} in region {codebuild_region}"
                }
                # Record the invocation - not a followup
                self._record_invocation('codebuild_direct', False, original_args, result)
                return result
            
            self.logger.debug(f"CodeBuild project started with build ID: {build_id}")
            
            # Record the build start - not a followup
            start_result = {
                'status': True,
                'build_id': build_id,
                'build_status': 'IN_PROGRESS',
                'output': f"Started CodeBuild project {project_name} build {build_id}"
            }
            self._record_invocation('codebuild_direct', False, original_args, start_result)
            
            # Wait for build to complete
            build_complete = False
            build_status = None
            max_attempts = 600  # 10 minutes at 1 second intervals
            attempts = 0
            
            while not build_complete and attempts < max_attempts:
                # Get build status
                build_info = codebuild_client.batch_get_builds(ids=[build_id])
                
                if 'builds' in build_info and len(build_info['builds']) > 0:
                    build_data = build_info['builds'][0]
                    build_status = build_data.get('buildStatus')
                    
                    if build_status in ['SUCCEEDED', 'FAILED', 'FAULT', 'TIMED_OUT', 'STOPPED']:
                        build_complete = True
                        build_phases = build_data.get('phases', [])
                        logs_info = build_data.get('logs', {})
                        
                        # Prepare result
                        result = {
                            'status': build_status == 'SUCCEEDED',
                            'build_id': build_id,
                            'build_status': build_status,
                            'project_name': project_name,
                            'start_time': build_data.get('startTime'),
                            'done': True,
                            'end_time': build_data.get('endTime'),
                            'phases': build_phases
                        }

                        # Record the final result - this is a followup
                        self._record_invocation('codebuild_direct', True, {'build_id': build_id}, result)

                        return result
                
                # Sleep before checking again
                time.sleep(1)
                attempts += 1
                
                # Every 30 seconds, record a status update
                if attempts % 30 == 0:
                    status_result = {
                        'status': True,
                        'build_id': build_id,
                        'build_status': 'IN_PROGRESS',
                        'attempts': attempts,
                        'output': f"Waiting for CodeBuild project {project_name} build {build_id}"
                    }
                    # This is a followup
                    self._record_invocation('codebuild_direct', True, {'build_id': build_id}, status_result)
            
            # If we get here, the build didn't complete in time
            timeout_result = {
                'status': False,
                'build_id': build_id,
                'error': "Build did not complete in the allotted time",
                'output': f"Timeout waiting for CodeBuild project {project_name} build {build_id}"
            }
            # This is a followup
            self._record_invocation('codebuild_direct', True, {'build_id': build_id}, timeout_result)
            return timeout_result
                
        except Exception as e:
            self.logger.error(f"CodeBuild execution failed with exception: {str(e)}")
            self.clear_execution()
            result = {
                'status': False,
                'error': f"CodeBuild execution failed with exception: {str(e)}",
                'output': f"Exception when executing CodeBuild project {project_name} in region {codebuild_region}: {str(e)}"
            }
            # Record the invocation - not a followup
            self._record_invocation('codebuild_direct', False, original_args, result)
            return result
    
    def clear_execution(self):
        """
        Clear all S3 objects related to a specific execution.

        Returns:
            int: Number of objects deleted, or -1 if an error occurred
        """

        try:
            # Only attempt to clear if we have an execution_id and output_bucket
            if not self.execution_id or not self.output_bucket:
                return 0

            # Delete entire execution directory from S3
            s3_client = boto3.client('s3')
            execution_prefix = f"executions/{self.execution_id}/"

            self.logger.info(f"Deleting execution directory for {self.execution_id}")

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
                self.logger.info(f"Deleted {len(objects_to_delete)} objects from execution directory")
                return len(objects_to_delete)
            else:
                self.logger.info(f"No existing objects found for execution {self.execution_id}")
                return 0
        except:
            self.logger.error("failed to clear execution s3 buckets")

    @aws_executor(execution_type="lambda")
    def exec_lambda(self, **kwargs):
        """
        Execute infrastructure operation through AWS Lambda.

        Executes the operation via AWS Lambda. If execution_id is provided at init time,
        this will use asynchronous execution with S3 tracking. Otherwise, it will
        execute synchronously and return the result directly.

        Args:
            **kwargs: Operation parameters including:
                - method: Operation method (create, destroy, etc.)
                - build_env_vars: Environment variables for the build
                - ssm_name: SSM parameter name (if applicable)

                Or Lambdabuild invocation configuration:
                - FunctionName: Lambda function name
                - Payload: JSON payload or string with commands and environment variables
                
        Returns:
            dict: Execution result or tracking information depending on execution mode
        """
        self.logger.warn(f"exec_lambda should be handled by decorator or bypassed in sync mode")

    @aws_executor(execution_type="codebuild")
    def exec_codebuild(self, **kwargs):
        """
        Execute infrastructure operation through AWS CodeBuild.
        
        Executes the operation via AWS CodeBuild. If execution_id is provided at init time,
        this will use asynchronous execution with S3 tracking. Otherwise, it will
        execute synchronously and return the result directly.
        
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
            dict: Execution result or tracking information depending on execution mode
        """
        self.logger.warn(f"exec_codebuild should be handled by decorator or bypassed in sync mode")

    def check_execution_status(self,execution_type="lambda"):
        """
        Check the status of an execution.
        
        Returns:
            dict: Status information for the execution, or empty dict in sync mode
        """
        if not self.execution_id or not self.output_bucket:
            return {}
            
        status_result = get_execution_status(
            execution_type,
            self.execution_id,
            self.output_bucket
        )
        
        # Record this as a followup check
        self._record_invocation(
            'status_check',
             True,
            {'execution_id': self.execution_id},
            status_result
        )

        return status_result

    def _execute_sync(self,execution_type="lambda",**kwargs):

        if execution_type == "lambda":
            # Direct execution will handle recording
            result = self._direct_lambda_execution(**kwargs)
        elif execution_type == "codebuild":
            # Direct execution will handle recording
            result = self._direct_codebuild_execution(**kwargs)
        else:
            raise ValueError(f"Unsupported execution_type: {execution_type}")

        status_result = self.check_execution_status(execution_type)

        if status_result.get("done"):
            self.clear_execution()
            return status_result["results"]

        if "body" in result:
            return result["body"]
        else:
            return result

    def execute(self, execution_type="lambda", async_mode=None, **kwargs):
        """
        Unified execution method that automatically uses sync or async mode
        based on whether execution_id was provided at init time.
        
        Args:
            execution_type (str): "lambda" or "codebuild"
            async_mode (bool, optional): If True, forces asynchronous execution
            **kwargs: Parameters for the execution
            
        Returns:
            dict: Execution result or tracking information
        """

        # sync or traditional execution
        if not async_mode:
            return self._execute_sync(execution_type,**kwargs)

        # Store original args for history
        original_args = kwargs.copy()
        original_args['execution_type'] = execution_type

        # Otherwise use the async decorated methods
        if execution_type == "lambda":
            result = self.exec_lambda(**kwargs)
        elif execution_type == "codebuild":
            result = self.exec_codebuild(**kwargs)
        else:
            raise ValueError(f"Unsupported execution_type: {execution_type}")

        # Record the execution since decorator can't do it directly
        self._record_invocation(f'{execution_type}_async',
                                False,
                                original_args,
                                result)

        return result

    def get_invocation_history(self, execution_id=None):
        """
        Get the invocation history for a specific execution ID from S3
        
        Args:
            execution_id (str, optional): Execution ID to retrieve history for.
                                        If None, uses this executor's execution_id.
        
        Returns:
            list: List of invocation records or empty list if not found
        """
        if execution_id is None:
            execution_id = self.execution_id
            
        if not execution_id or not self.output_bucket:
            return []
            
        # Load from S3
        try:
            s3_client = boto3.client('s3')
            history_key = f"executions/invocations/{execution_id}/invocation_history.json"
            
            history = _s3_get_object(s3_client, self.output_bucket, history_key)
            if isinstance(history, dict) and 'invocations' in history:
                return history['invocations']
        except:
            pass
                
        return []

    def get_last_invocation(self, execution_id=None, only_initial=False):
        """
        Get the most recent invocation record from S3
        
        Args:
            execution_id (str, optional): Execution ID to retrieve history for.
                                        If None, uses this executor's execution_id.
            only_initial (bool): If True, return only non-followup invocations
        
        Returns:
            dict: The most recent invocation record or None if no invocations
        """
        history = self.get_invocation_history(execution_id)
        
        if not history:
            return None
            
        if not only_initial:
            return history[-1]
            
        # Filter for only initial (non-followup) invocations
        initial_invocations = [record for record in history if not record.get('is_followup')]
        if initial_invocations:
            return initial_invocations[-1]
            
        return None