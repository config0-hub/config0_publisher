import boto3
import json
import uuid
import time
from datetime import datetime, timezone, timedelta
from botocore.exceptions import ClientError

class StepFuncIacOrchestrator:
    """
    Class for orchestrating infrastructure as code executions via Step Functions.
    This class can be inherited and extended for specific use cases.
    """
    
    def __init__(self, 
                state_machine_name=None,
                state_machine_arn=None, 
                s3_bucket="config0-executions", 
                region="us-east-1",
                account_id=None):
        """
        Initialize the orchestrator with AWS configuration.
        
        Args:
            state_machine_name (str): Name of the Step Function state machine (alternative to state_machine_arn)
            state_machine_arn (str): ARN of the Step Function state machine
            s3_bucket (str): Default S3 bucket for temporary file storage
            region (str): AWS region
            account_id (str): AWS account ID (auto-detected if None)
        """
        self.region = region
        self.s3_bucket = s3_bucket
        
        # Initialize AWS clients
        self.sfn_client = boto3.client('stepfunctions', region_name=region)
        self.lambda_client = boto3.client('lambda', region_name=region)
        self.codebuild_client = boto3.client('codebuild', region_name=region)
        self.s3_client = boto3.client('s3', region_name=region)
        
        # Set up Step Function ARN
        if state_machine_arn:
            self.state_machine_arn = state_machine_arn
        elif state_machine_name:
            # If account ID is not provided, get it
            if not account_id:
                sts_client = boto3.client('sts', region_name=region)
                account_id = sts_client.get_caller_identity()["Account"]
            
            # Construct the Step Function ARN from name, region and account ID
            self.state_machine_arn = f"arn:aws:states:{region}:{account_id}:stateMachine:{state_machine_name}"
            print(f"Using Step Function ARN: {self.state_machine_arn}")
        else:
            # We'll allow None for now, but invoke_step_function will validate this later
            self.state_machine_arn = None
    
    def _generate_execution_name(self, prefix="config0-exec"):
        """
        Generate a unique execution name.
        
        Args:
            prefix (str): Prefix for the execution name
            
        Returns:
            str: A unique execution name
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"{prefix}-{timestamp}-{str(uuid.uuid4())[:8]}"
    
    def _generate_s3_key(self, execution_type):
        """
        Generate a unique S3 key.
        
        Args:
            execution_type (str): Type of execution (lambda or codebuild)
            
        Returns:
            str: A unique S3 key
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"executions/{execution_type}/{timestamp}-{str(uuid.uuid4())[:8]}"
    
    def _get_timestamp_seconds_from_now(self, minutes=60):
        """
        Calculate a timestamp that is a certain number of minutes from now.
        Returns epoch time (seconds since Jan 1, 1970 UTC).
        
        Args:
            minutes (int): Number of minutes from now
            
        Returns:
            int: Unix timestamp in seconds (epoch time)
        """
        future_time = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        return int(future_time.timestamp())
    
    def _is_build_expired(self, build_expire_at):
        """
        Check if a build has expired based on the expiry timestamp.
        
        Args:
            build_expire_at (int): Expiry timestamp in epoch time (seconds since Jan 1, 1970 UTC)
            
        Returns:
            bool: True if expired, False otherwise
        """
        if not build_expire_at:
            return False
            
        current_time = int(datetime.now(timezone.utc).timestamp())
        return current_time > build_expire_at
    
    def invoke_step_function(self, execution_params, execution_name=None, expiry_minutes=60):
        """
        Invokes the orchestrator Step Function with the provided parameters.
        
        Args:
            execution_params (dict): Parameters for the execution
            execution_name (str): Optional name for the execution (generated if None)
            expiry_minutes (int): Minutes until the execution should be considered expired
        
        Returns:
            dict: Response from the Step Function execution start
        """
        if self.state_machine_arn is None:
            raise ValueError("state_machine_arn must be set")
        
        # Generate a unique execution name if not provided
        if execution_name is None:
            execution_name = self._generate_execution_name()
        
        # Add build expiry timestamp if not already present
        if "build_expire_at" not in execution_params:
            execution_params["build_expire_at"] = self._get_timestamp_seconds_from_now(expiry_minutes)
        
        # Start execution
        response = self.sfn_client.start_execution(
            stateMachineArn=self.state_machine_arn,
            name=execution_name,
            input=json.dumps(execution_params)
        )
        
        print(f"Started Step Function execution: {execution_name}")
        print(f"Execution ARN: {response['executionArn']}")
        print(f"Will expire at: {datetime.fromtimestamp(execution_params['build_expire_at']).strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Store initial parameters in S3 if S3 details are provided
        if "S3_TMP_BUCKET" in execution_params and "S3_TMP_BUCKET_KEY" in execution_params:
            self._store_execution_params_in_s3(
                execution_params["S3_TMP_BUCKET"],
                execution_params["S3_TMP_BUCKET_KEY"],
                execution_params
            )
        
        return response
    
    def _store_execution_params_in_s3(self, bucket, key, params, params_suffix="_params.json"):
        """
        Store execution parameters in S3 for reference.
        
        Args:
            bucket (str): S3 bucket name
            key (str): Base S3 key
            params (dict): Execution parameters
            params_suffix (str): Suffix for the parameters file
            
        Returns:
            bool: True if successful, False otherwise
        """
        params_key = f"{key}{params_suffix}"
        
        try:
            self.s3_client.put_object(
                Bucket=bucket,
                Key=params_key,
                Body=json.dumps(params, default=str).encode('utf-8'),
                ContentType='application/json'
            )
            print(f"Stored execution parameters in S3: {bucket}/{params_key}")
            return True
        except Exception as e:
            print(f"Error storing execution parameters in S3: {str(e)}")
            return False
    
    def invoke_with_lambda(self,
                        lambda_function_name="config0-iac",
                        payload=None,
                        s3_key=None,
                        s3_bucket=None,
                        expiry_minutes=60):
        """
        Invokes the Step Function to execute a Lambda function.
        
        Args:
            lambda_function_name (str): Name of the Lambda function to execute
            payload (dict): Payload to pass to the Lambda function
            s3_key (str): S3 key for temporary storage (generated if None)
            s3_bucket (str): S3 bucket for temporary storage (uses default if None)
            expiry_minutes (int): Minutes until the execution should be considered expired
            
        Returns:
            dict: Response from the Step Function execution start
        """
        # Use default values if not provided
        if payload is None:
            payload = {}
            
        if s3_bucket is None:
            s3_bucket = self.s3_bucket
            
        # Generate a unique S3 key if not provided
        if s3_key is None:
            s3_key = self._generate_s3_key("lambda")
        
        # Prepare execution parameters
        execution_params = {
            "execution_type": "use_lambda",
            "lambda_function_name": lambda_function_name,
            "payload": payload,
            "S3_TMP_BUCKET": s3_bucket,
            "S3_TMP_BUCKET_KEY": s3_key,
            "build_expire_at": self._get_timestamp_seconds_from_now(expiry_minutes)
        }
        
        return self.invoke_step_function(execution_params)
    
    def invoke_with_codebuild(self,
                            codebuild_project_name="config0-iac",
                            env_vars_override=None,
                            s3_key=None,
                            s3_bucket=None,
                            timeout_override=None,
                            image_override=None,
                            compute_type_override=None,
                            environment_type_override=None,
                            buildspec_override=None,
                            expiry_minutes=60):
        """
        Invokes the Step Function to execute a CodeBuild project.
        
        Args:
            codebuild_project_name (str): Name of the CodeBuild project to execute
            env_vars_override (dict): Environment variables to pass to the CodeBuild project
            s3_key (str): S3 key for temporary storage (generated if None)
            s3_bucket (str): S3 bucket for temporary storage (uses default if None)
            timeout_override (int): Optional timeout override in minutes
            image_override (str): Optional container image override
            compute_type_override (str): Optional compute type override
            environment_type_override (str): Optional environment type override
            buildspec_override (str): Optional buildspec override
            expiry_minutes (int): Minutes until the execution should be considered expired
            
        Returns:
            dict: Response from the Step Function execution start
        """
        # Use default values if not provided
        if env_vars_override is None:
            env_vars_override = {}
            
        if s3_bucket is None:
            s3_bucket = self.s3_bucket
            
        # Generate a unique S3 key if not provided
        if s3_key is None:
            s3_key = self._generate_s3_key("codebuild")
        
        # Prepare execution parameters
        execution_params = {
            "execution_type": "use_codebuild",
            "codebuild_project_name": codebuild_project_name,
            "env_vars_override": env_vars_override,
            "S3_TMP_BUCKET": s3_bucket,
            "S3_TMP_BUCKET_KEY": s3_key,
            "build_expire_at": self._get_timestamp_seconds_from_now(expiry_minutes)
        }
        
        # Add optional overrides if provided
        if timeout_override is not None:
            execution_params["timeout_override"] = timeout_override
        
        if image_override is not None:
            execution_params["image_override"] = image_override
            
        if compute_type_override is not None:
            execution_params["compute_type_override"] = compute_type_override
            
        if environment_type_override is not None:
            execution_params["environment_type_override"] = environment_type_override
            
        if buildspec_override is not None:
            execution_params["buildspec_override"] = buildspec_override
        
        return self.invoke_step_function(execution_params)
    
    def get_status_from_s3(self, bucket, key, status_suffix="_status.json", result_suffix="_result.json", log_suffix="_log.txt"):
        """
        Retrieve status, logs, and results from S3 bucket according to the specified format.
        
        Args:
            bucket (str): S3 bucket name
            key (str): Base S3 key
            status_suffix (str): Suffix for the status file
            result_suffix (str): Suffix for the result file
            log_suffix (str): Suffix for the log file
            
        Returns:
            dict: Status information in the format:
                  {"log": <log content>, "status": <execution status>, "stepf_status": True/False/None}
        """
        status_key = f"{key}{status_suffix}"
        result_key = f"{key}{result_suffix}"
        log_key = f"{key}{log_suffix}"
        
        # Get execution parameters to check expiry time
        execution_params = self._get_execution_params_for_s3(bucket, key)
        build_expire_at = execution_params.get('build_expire_at') if execution_params else None
        
        # Check if build has expired
        if build_expire_at and self._is_build_expired(build_expire_at):
            return {
                "stepf_status": False,
                "status": "TIMED_OUT",
                "log": f"Execution timed out. Expiry time was: {datetime.fromtimestamp(build_expire_at).strftime('%Y-%m-%d %H:%M:%S')}",
                "expired_at": build_expire_at
            }
        
        # Try to get the status file
        status_data = None
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=status_key)
            status_data = json.loads(response['Body'].read().decode('utf-8'))
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                # Status file doesn't exist yet
                pass
            else:
                print(f"Error retrieving status from S3 {bucket}/{status_key}: {str(e)}")
        
        # Try to get the result file
        result_data = None
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=result_key)
            result_data = json.loads(response['Body'].read().decode('utf-8'))
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                # Result file doesn't exist yet
                pass
            else:
                print(f"Error retrieving result from S3 {bucket}/{result_key}: {str(e)}")
        
        # Try to get the log file
        log_data = None
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=log_key)
            log_data = response['Body'].read().decode('utf-8')
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                # Log file doesn't exist yet
                pass
            else:
                print(f"Error retrieving log from S3 {bucket}/{log_key}: {str(e)}")
        
        # If neither status nor result exists, build hasn't completed yet
        if status_data is None and result_data is None and log_data is None:
            return {"stepf_status": None}
        
        # Determine the status based on available data
        status = None
        if status_data and 'status' in status_data:
            status = status_data['status']
        elif result_data and 'status' in result_data:
            status = result_data['status']
        
        # Map completion status to stepf_status
        stepf_status = None
        if status:
            # Consider as completed (stepf_status=True) if we have a valid status
            if status in ["COMPLETED", "SUCCEEDED", "FAILED", "TIMED_OUT", "ERROR"]:
                stepf_status = True
            # If the status is "RUNNING" or another non-terminal state, keep stepf_status as None
            elif status in ["UNKNOWN", "NOT_FOUND"]:
                stepf_status = None
        
        # If we have status data but no valid status determined, check for errors
        if stepf_status is None and status_data and 'error' in status_data:
            stepf_status = False
            status = "ERROR" if not status else status
        
        # Combine log data
        log = ""
        if log_data:
            log = log_data
        elif result_data and 'logs' in result_data:
            # If logs are in the result data as an array, join them
            if isinstance(result_data['logs'], list):
                log = "\n".join(result_data['logs'])
            else:
                log = str(result_data['logs'])
        elif status_data and 'message' in status_data:
            log = status_data['message']
        
        # Build the response
        response = {
            "stepf_status": stepf_status
        }
        
        if status:
            response["status"] = status
        
        if log:
            response["log"] = log
        
        if result_data:
            # If there are logs in the result data and we've already included them in the 'log' field,
            # remove them from the result to avoid duplication
            if 'logs' in result_data and log:
                result_copy = result_data.copy()
                if 'logs' in result_copy:
                    del result_copy['logs']
                response["result"] = result_copy
            else:
                response["result"] = result_data
        
        if status_data:
            # Similar to above, avoid duplication of data
            status_copy = status_data.copy()
            if 'message' in status_copy and log:
                del status_copy['message']
            response["status_details"] = status_copy
        
        return response
    
    def _get_execution_params_for_s3(self, bucket, key, params_suffix="_params.json"):
        """
        Retrieve the original execution parameters from S3.
        
        Args:
            bucket (str): S3 bucket name
            key (str): Base S3 key
            params_suffix (str): Suffix for the parameters file
            
        Returns:
            dict: Execution parameters or None if not found
        """
        params_key = f"{key}{params_suffix}"
        
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=params_key)
            return json.loads(response['Body'].read().decode('utf-8'))
        except Exception:
            # If no parameters file exists, try to check for build_expire_at in status file
            try:
                status_key = f"{key}_status.json"
                response = self.s3_client.get_object(Bucket=bucket, Key=status_key)
                status_data = json.loads(response['Body'].read().decode('utf-8'))
                if 'updated_at' in status_data:
                    # Convert updated_at to build_expire_at by adding 60 minutes
                    updated_at = status_data.get('updated_at')
                    if isinstance(updated_at, int):
                        return {'build_expire_at': updated_at + (60 * 60)}  # Add 1 hour
                elif 'build_expire_at' in status_data:
                    return {'build_expire_at': status_data['build_expire_at']}
            except Exception:
                pass
            
            return None
    
    def retrieve_execution_status(self, s3_bucket, s3_key, execution_arn=None):
        """
        Retrieve execution status primarily from S3, with option to check Step Function status.
        
        Args:
            s3_bucket (str): S3 bucket name
            s3_key (str): Base S3 key
            execution_arn (str): Optional Step Function execution ARN to check
            
        Returns:
            dict: Status information with log, status and stepf_status
        """
        # Primary method: Check S3 for status files
        s3_status = self.get_status_from_s3(s3_bucket, s3_key)
        
        # If we have a definitive status from S3, return it
        if s3_status["stepf_status"] is not None:  # Either True or False
            return s3_status
        
        # If we have an execution ARN, check Step Function status as a backup
        if execution_arn:
            try:
                sfn_status = self.check_execution_status(execution_arn)
                
                # Extract S3 bucket and key from the execution input if available
                s3_bucket_from_sfn = None
                s3_key_from_sfn = None
                
                if "input" in sfn_status:
                    try:
                        input_data = json.loads(sfn_status["input"])
                        s3_bucket_from_sfn = input_data.get("S3_TMP_BUCKET")
                        s3_key_from_sfn = input_data.get("S3_TMP_BUCKET_KEY")
                    except:
                        pass
                
                # If we got S3 info from the Step Function and it's different from what was provided,
                # check that location too
                if (s3_bucket_from_sfn and s3_key_from_sfn and 
                    (s3_bucket_from_sfn != s3_bucket or s3_key_from_sfn != s3_key)):
                    alt_s3_status = self.get_status_from_s3(s3_bucket_from_sfn, s3_key_from_sfn)
                    if alt_s3_status["stepf_status"] is not None:
                        return alt_s3_status
                
                # Check if execution has completed
                if sfn_status["status"] in ["SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"]:
                    # Execution completed but no S3 status found - this is unusual
                    log_message = f"Step Function execution {execution_arn} finished with status {sfn_status['status']}, but no status files found in S3."
                    
                    if sfn_status["status"] == "SUCCEEDED":
                        return {
                            "stepf_status": True,
                            "status": "SUCCEEDED",
                            "log": log_message,
                            "sfn_details": sfn_status
                        }
                    else:
                        return {
                            "stepf_status": False,
                            "status": sfn_status["status"],
                            "log": log_message,
                            "error": sfn_status.get("error", "Unknown error"),
                            "sfn_details": sfn_status
                        }
                
                # Check for timeout based on build_expire_at
                if "input" in sfn_status:
                    try:
                        input_data = json.loads(sfn_status["input"])
                        build_expire_at = input_data.get("build_expire_at")
                        
                        if build_expire_at and self._is_build_expired(build_expire_at):
                            return {
                                "stepf_status": False,
                                "status": "TIMED_OUT",
                                "log": f"Execution timed out. Expiry time was: {datetime.fromtimestamp(build_expire_at).strftime('%Y-%m-%d %H:%M:%S')}",
                                "expired_at": build_expire_at
                            }
                    except Exception:
                        pass
                
                # Still running
                return {
                    "stepf_status": None,
                    "sfn_status": sfn_status["status"],
                    "log": f"Execution {execution_arn} is still running."
                }
                
            except Exception as e:
                # Error checking Step Function status
                return {
                    "stepf_status": None,
                    "error": f"Error checking Step Function status: {str(e)}"
                }
        
        # If we get here, we couldn't determine status definitely
        return {"stepf_status": None}
    
    def check_execution_status(self, execution_arn):
        """
        Checks the status of a Step Function execution.
        
        Args:
            execution_arn (str): ARN of the Step Function execution
            
        Returns:
            dict: Current status of the execution
        """
        response = self.sfn_client.describe_execution(
            executionArn=execution_arn
        )
        
        status = response['status']
        
        # Parse the input to get the S3 bucket and key
        input_data = json.loads(response['input'])
        
        result = {
            "status": status,
            "execution_arn": execution_arn,
            "started_at": response['startDate'],
            "input": response['input']
        }
        
        if status != 'RUNNING':
            result["stopped_at"] = response.get('stopDate')
        
        if status == 'SUCCEEDED':
            # If execution succeeded, parse the output to get results
            result["output"] = response['output']
            print(f"Execution {execution_arn} succeeded")
        elif status == 'FAILED':
            # If execution failed, get error details
            result["error"] = response.get('error', 'Unknown error')
            result["cause"] = response.get('cause', 'Unknown cause')
            print(f"Execution {execution_arn} failed: {result['error']} - {result['cause']}")
        else:
            # Execution is still running or in another state
            print(f"Execution {execution_arn} is {status}")
        
        return result
    
    def put_status_to_s3(self, bucket, key, status_data, status_suffix="_status.json"):
        """
        Write status data to S3 bucket.
        
        Args:
            bucket (str): S3 bucket name
            key (str): Base S3 key
            status_data (dict): Status data to write
            status_suffix (str): Suffix to append to the key for the status file
            
        Returns:
            bool: True if successful, False otherwise
        """
        status_key = f"{key}{status_suffix}"
        
        # Add timestamp and updated_at if not present
        if 'timestamp' not in status_data:
            status_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        if 'updated_at' not in status_data:
            status_data['updated_at'] = int(time.time())
        
        try:
            self.s3_client.put_object(
                Bucket=bucket,
                Key=status_key,
                Body=json.dumps(status_data, default=str).encode('utf-8'),
                ContentType='application/json'
            )
            print(f"Wrote status to S3: {bucket}/{status_key}")
            return True
            
        except Exception as e:
            print(f"Error writing status to S3 {bucket}/{status_key}: {str(e)}")
            return False
    
    def put_logs_to_s3(self, bucket, key, logs, log_suffix="_log.txt"):
        """
        Write logs to S3 bucket.
        
        Args:
            bucket (str): S3 bucket name
            key (str): Base S3 key
            logs (str or list): Log content (string or list of strings)
            log_suffix (str): Suffix to append to the key for the log file
            
        Returns:
            bool: True if successful, False otherwise
        """
        log_key = f"{key}{log_suffix}"
        
        # Convert logs to string if it's a list
        if isinstance(logs, list):
            log_content = "\n".join(logs)
        else:
            log_content = str(logs)
        
        try:
            self.s3_client.put_object(
                Bucket=bucket,
                Key=log_key,
                Body=log_content.encode('utf-8'),
                ContentType='text/plain'
            )
            print(f"Wrote logs to S3: {bucket}/{log_key}")
            return True
            
        except Exception as e:
            print(f"Error writing logs to S3 {bucket}/{log_key}: {str(e)}")
            return False
    
    def update_execution_status(self, s3_bucket, s3_key, status, logs=None, error=None, additional_data=None):
        """
        Update execution status and logs in S3.
        
        Args:
            s3_bucket (str): S3 bucket name
            s3_key (str): Base S3 key
            status (str): Execution status
            logs (str or list): Optional logs to write
            error (str): Optional error message
            additional_data (dict): Optional additional data to include in status
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Prepare status data
        status_data = {
            "status": status,
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "updated_at": int(time.time())
        }
        
        if error:
            status_data["error"] = error
        
        if additional_data:
            status_data.update(additional_data)
        
        # Write status to S3
        status_success = self.put_status_to_s3(s3_bucket, s3_key, status_data)
        
        # Write logs to S3 if provided
        log_success = True
        if logs:
            log_success = self.put_logs_to_s3(s3_bucket, s3_key, logs)
        
        return status_success and log_success
    
    def wait_for_execution_completion(self, execution_arn=None, s3_bucket=None, s3_key=None, poll_interval=5, timeout=300):
        """
        Waits for a Step Function execution to complete, polling at the specified interval.
        Can wait based on either Step Function ARN or S3 bucket/key.
        
        Args:
            execution_arn (str): ARN of the Step Function execution
            s3_bucket (str): S3 bucket for checking status
            s3_key (str): S3 key for checking status
            poll_interval (int): Time in seconds between status checks
            timeout (int): Maximum time to wait in seconds
            
        Returns:
            dict: Final status of the execution
        """
        if not execution_arn and (not s3_bucket or not s3_key):
            raise ValueError("Either execution_arn or both s3_bucket and s3_key must be provided")
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if s3_bucket and s3_key:
                status_response = self.retrieve_execution_status(s3_bucket, s3_key, execution_arn)
                
                # If we have a definitive status from S3, return it
                if status_response["stepf_status"] is not None:  # Either True or False
                    return status_response
            elif execution_arn:
                status_response = self.check_execution_status(execution_arn)
                
                if status_response['status'] in ['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'ABORTED']:
                    return status_response
                
                # Check for timeout based on build_expire_at
                try:
                    input_data = json.loads(status_response['input'])
                    build_expire_at = input_data.get('build_expire_at')
                    
                    if build_expire_at and self._is_build_expired(build_expire_at):
                        return {
                            "stepf_status": False,
                            "status": "TIMED_OUT",
                            "log": f"Execution timed out. Expiry time was: {datetime.fromtimestamp(build_expire_at).strftime('%Y-%m-%d %H:%M:%S')}",
                            "expired_at": build_expire_at
                        }
                except Exception:
                    pass
            
            print(f"Execution still running. Time elapsed: {int(time.time() - start_time)}s")
            time.sleep(poll_interval)
        
        print(f"Timeout reached after {timeout} seconds. Execution is still running.")
        return {
            "stepf_status": None,
            "status": "TIMEOUT_WAITING"
        }