def get_execution_status(self, resource_type=None, resource_id=None, output_bucket=None, execution_id=None):
    """
    Get the status of an execution from S3.
    
    Args:
        resource_type (str, optional): Resource type for deterministic execution ID generation
        resource_id (str, optional): Resource ID for deterministic execution ID generation
        output_bucket (str, optional): S3 bucket to check for status
        execution_id (str, optional): Specific execution ID to check
    
    Returns:
        dict: Execution status information
    """
    # Set defaults to class attributes if not provided
    if not resource_type:
        resource_type = getattr(self, 'resource_type', None)
    
    if not resource_id:
        resource_id = getattr(self, 'resource_id', None)
    
    # Generate execution_id if not provided
    if not execution_id:
        if not resource_type or not resource_id:
            self.logger.error("Cannot get execution status: No execution_id provided and resource_type/resource_id not available")
            return None
        
        # Create deterministic execution ID based on resource identifiers
        base_string = f"{resource_type}:{resource_id}"
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
            self.logger.error("No output bucket specified for status check")
            return None
    
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
            result["status"] = "in_progress"  # If initiated but not done, it's in progress
            
            # If execution has a build_id, include it
            if 'build_id' in initiated_data:
                result["build_id"] = initiated_data['build_id']
            
            # Update result structure with additional initiated data
            for key in ['resource_type', 'resource_id', 'method', 'execution_type']:
                if key in initiated_data:
                    result[key] = initiated_data[key]
            
        except s3_client.exceptions.NoSuchKey:
            self.logger.debug(f"No initiated marker found for execution {execution_id}")
        
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
                    result["status"] = "completed" if result["success"] else "failed"
                    
                    if 'end_time' in done_json:
                        result["completed_time"] = done_json['end_time']
                    
                    # Copy any other fields from done_json to result
                    for key, value in done_json.items():
                        if key not in result:
                            result[key] = value
            except json.JSONDecodeError:
                # If it's not JSON, use the raw content
                success_value = done_data.strip().lower() in ['success', 'true']
                result["success"] = success_value
                result["status"] = "completed" if success_value else "failed"
            
            # Calculate elapsed time if we have both start and end times
            if result["initiated_time"] and result["completed_time"]:
                result["elapsed_time"] = result["completed_time"] - result["initiated_time"]
            
        except s3_client.exceptions.NoSuchKey:
            self.logger.debug(f"No done marker found for execution {execution_id}")
        
        # If we found an initiated marker but no done marker, calculate elapsed time from now
        if result["initiated_time"] and not result["completed_time"]:
            result["elapsed_time"] = time.time() - result["initiated_time"]
            
        return result
        
    except Exception as e:
        self.logger.error(f"Error checking execution status: {str(e)}")
        result["error"] = str(e)
        return result