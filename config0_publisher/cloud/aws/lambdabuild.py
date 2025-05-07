#!/usr/bin/env python

import re
import json
from time import time
import logging

from config0_publisher.serialization import b64_encode
from config0_publisher.serialization import b64_decode
from config0_publisher.cloud.aws.common import AWSCommonConn

class LambdaResourceHelper(AWSCommonConn):
    """Helper class for AWS Lambda resource operations."""

    def __init__(self, **kwargs):
        """Initialize the Lambda resource helper with default values and configurations."""
        default_values = {
            "lambda_function_name": "config0-iac"
        }

        AWSCommonConn.__init__(self,
                             default_values=default_values,
                             set_env_vars=self.get_set_env_vars(),
                             **kwargs)

        self.init_env_vars = kwargs.get("init_env_vars")
        
        if "cmds" not in kwargs:
            raise ValueError("Required parameter 'cmds' is missing")
            
        self.cmds_b64 = b64_encode(kwargs["cmds"])

        try:
            self.logs_client = self.session.client('logs')
        except Exception as e:
            self.logger.error(f"Failed to create logs client: {str(e)}")
            raise

        if not self.results["inputargs"].get("lambda_function_name"):
            self.results["inputargs"]["lambda_function_name"] = self.lambda_function_name

    @staticmethod
    def get_set_env_vars():
        """Define environment variables needed for Lambda execution."""
        return {
            "tmp_bucket": True,
            "log_bucket": True,
            "app_dir": None,
            "stateful_id": None,
            "remote_stateful_bucket": None,
            "lambda_function_name": None,
            "run_share_dir": None,
            "share_dir": None
        }

    def _env_vars_to_lambda_format(self):
        """Convert environment variables to format required by Lambda."""
        skip_keys = ["AWS_ACCESS_KEY_ID",
                      "AWS_SECRET_ACCESS_KEY",
                      "AWS_SESSION_TOKEN"]

        minimum_keys = ["STATEFUL_ID",
                        "REMOTE_STATEFUL_BUCKET",
                        "TMPDIR",
                        "APP_DIR",
                        "SSM_NAME"]

        if self.init_env_vars:
            env_vars = self.init_env_vars
        else:
            env_vars = {}

        env_vars["OUTPUT_BUCKET"] = self.tmp_bucket
        env_vars["OUTPUT_BUCKET_KEY"] = self.s3_output_key
        env_vars["BUILD_EXPIRE_AT"] = str(int(self.build_expire_at))
        env_vars["BUILD_TIMEOUT"] = str(int(self.build_timeout))

        _added = []

        if not hasattr(self, 'build_env_vars') or not self.build_env_vars:
            return env_vars

        pattern = r"^AWS_LAMBDA_"

        for _k, _v in self.build_env_vars.items():
            if not _v:
                self.logger.debug(f"env var {_k} is empty/None - skipping")
                continue

            if _k in skip_keys:
                continue

            if _k not in minimum_keys:
                continue

            if re.search(pattern, _k):
                continue

            # cannot duplicate env vars
            if _k in _added:
                continue

            _added.append(_k)
            env_vars[_k] = _v

        # determine defaults
        if not env_vars.get("TMPDIR"):
            env_vars["TMPDIR"] = "/tmp"

        if not env_vars.get("APP_DIR") and self.build_env_vars.get("APP_NAME"):
            env_vars["APP_DIR"] = f"var/tmp/{self.build_env_vars['APP_NAME']}"

        # we need to provide this for lambda to work
        if not env_vars.get("APP_DIR"):
            env_vars["APP_DIR"] = "var/tmp/terraform"

        return env_vars

    def _get_timeout(self):
        """Calculate and validate the build timeout."""
        # we limit the build to 800 seconds, which is one min
        # less than 10 minutes
        try:
            timeout = int(self.build_timeout)
            self.logger.debug(f"_get_timeout - using user specified timeout {timeout}s")
        except (ValueError, AttributeError, TypeError) as e:
            self.logger.debug("_get_timeout - using default of 800s")
            timeout = 800

        if timeout > 800:
            self.logger.debug(f"_get_timeout - timeout of {timeout} exceeds limit of 800s for lambda -> reseting to 800s")
            timeout = 800

        return timeout

    def _trigger_build(self):
        """Trigger the Lambda build process."""
        try:
            self.build_timeout = self._get_timeout()
            self.build_expire_at = time() + self._get_timeout()

            # Define the configuration for invoking the Lambda function
            env_vars = self._env_vars_to_lambda_format()

            self.logger.debug("#" * 32)
            self.logger.debug("# ref 324523453 env vars for lambda build")
            self.logger.json(env_vars)
            self.logger.debug("#" * 32)

            invocation_config = {
                'FunctionName': self.lambda_function_name,
                'InvocationType': 'RequestResponse',
                'LogType': 'Tail',
                'Payload': json.dumps(
                    {
                        "cmds_b64": self.cmds_b64,
                        "env_vars_b64": b64_encode(env_vars),
                    })
            }

            # TODO: add stop function in the future here
            return self.lambda_client.invoke(**invocation_config)
        except Exception as e:
            self.logger.error(f"Failed to trigger build: {str(e)}")
            raise

    def _submit(self):
        """Submit the build job to Lambda and process results."""
        self.phase_result = self.new_phase("submit")

        # we don't want to clobber the intact
        # stateful files from creation
        if hasattr(self, 'method') and self.method in ["create", "pre-create"]:
            try:
                self.upload_to_s3_stateful()
            except Exception as e:
                self.logger.error(f"Failed to upload to S3: {str(e)}")
                raise

        """
        options:
          - ResponseMetadata
          - StatusCode
          - LogResult
          - ExecutedVersion
          - Payload
        """

        try:
            self.response = self._trigger_build()
            lambda_status = int(self.response["StatusCode"])
            self.results["lambda_status"] = lambda_status

            payload = json.loads(self.response["Payload"].read().decode())

            try:
                lambda_results = json.loads(payload["body"])
            except (KeyError, json.JSONDecodeError, TypeError) as e:
                lambda_results = payload
                lambda_results["status"] = False
                self.results["failed_message"] = " ".join(lambda_results.get("stackTrace", ["Unknown error"]))
                self.results["output"] = " ".join(lambda_results.get("stackTrace", ["Unknown error"]))

            self.results["lambda_results"] = lambda_results

            if lambda_results.get("status") is True and lambda_status == 200:
                self.results["status"] = lambda_results["status"]
                self.results["exitcode"] = 0
            elif lambda_status != 200:
                self.results["status"] = False
                self.results["exitcode"] = "78"
                if not self.results.get("failed_message"):
                    self.results["failed_message"] = "lambda function failed"
            else:
                self.results["status"] = False
                self.results["exitcode"] = "79"
                if not self.results.get("failed_message"):
                    self.results["failed_message"] = "execution of cmd in lambda function failed"

            try:
                output = self.download_log_from_s3()
            except Exception as e:
                self.logger.warning(f"Failed to download log from S3, using LogResult instead: {str(e)}")
                output = b64_decode(self.response.get("LogResult", ""))

            if not self.results.get("output"):
                self.results["output"] = output

            return self.results
        except Exception as e:
            self.logger.error(f"Submit failed: {str(e)}")
            self.results["status"] = False
            self.results["failed_message"] = f"Lambda submission error: {str(e)}"
            self.results["exitcode"] = "99"
            return self.results

    def run(self):
        """Run the Lambda resource operation."""
        try:
            self._submit()

            if self.results.get("status") is False:
                if not hasattr(self, 'method'):
                    self.results["failed_message"] = "operation failed (method not specified)"
                elif self.method == "validate":
                    self.results["failed_message"] = "the resources have drifted"
                elif self.method == "check":
                    self.results["failed_message"] = "the resources failed check"
                elif self.method == "pre-create":
                    self.results["failed_message"] = "the resources failed pre-create"
                elif self.method == "apply":
                    self.results["failed_message"] = "applying of resources have failed"
                elif self.method == "create":
                    self.results["failed_message"] = "creation of resources have failed"
                elif self.method == "destroy":
                    self.results["failed_message"] = "destroying of resources have failed"

            return self.results
        except Exception as e:
            self.logger.error(f"Run operation failed: {str(e)}")
            self.results["status"] = False
            self.results["failed_message"] = f"Operation failed: {str(e)}"
            self.results["exitcode"] = "100"
            return self.results