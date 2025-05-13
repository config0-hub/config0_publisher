#!/usr/bin/env python

import re
import json
from time import time
from config0_publisher.serialization import b64_encode
from config0_publisher.cloud.aws.common import AWSCommonConn

class LambdaResourceHelper(AWSCommonConn):
    DEFAULT_VALUES = {
        "lambda_function_name": "config0-iac"
    }

    # Constants for environment variable filtering
    SKIP_KEYS = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
    MINIMUM_KEYS = ["STATEFUL_ID", "REMOTE_STATEFUL_BUCKET", "TMPDIR", "APP_DIR", "SSM_NAME"]
    MAX_LAMBDA_TIMEOUT = 800  # Maximum timeout in seconds

    def __init__(self, **kwargs):
        if not kwargs.get("cmds"):
            raise ValueError("'cmds' parameter is required")

        self.init_env_vars = kwargs.get("init_env_vars", {})
        self.cmds_b64 = b64_encode(kwargs["cmds"])
        self.build_env_vars = kwargs.get("build_env_vars", {})
        self.s3_output_key = kwargs.get("s3_output_key")
        self.build_timeout = kwargs.get("build_timeout")
        self.build_expire_at = None

        AWSCommonConn.__init__(
            self,
            default_values=self.DEFAULT_VALUES,
            set_env_vars=self.get_set_env_vars(),
            **kwargs
        )

        if not self.results["inputargs"].get("lambda_function_name"):
            self.results["inputargs"]["lambda_function_name"] = self.lambda_function_name

    @staticmethod
    def get_set_env_vars():
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
        env_vars = self.init_env_vars.copy() if self.init_env_vars else {}

        # Add required environment variables
        env_vars["OUTPUT_BUCKET"] = self.tmp_bucket
        env_vars["OUTPUT_BUCKET_KEY"] = self.s3_output_key
        env_vars["BUILD_EXPIRE_AT"] = str(int(self.build_expire_at))
        env_vars["BUILD_TIMEOUT"] = str(int(self.build_timeout))

        if not self.build_env_vars:
            return self._set_default_env_vars(env_vars)

        _added = []
        pattern = r"^AWS_LAMBDA_"

        for _k, _v in self.build_env_vars.items():
            if not _v:
                self.logger.debug(f"env var {_k} is empty/None - skipping")
                continue

            if (_k in self.SKIP_KEYS or 
                _k not in self.MINIMUM_KEYS or 
                re.search(pattern, _k) or 
                _k in _added):
                continue

            _added.append(_k)
            env_vars[_k] = _v

        return self._set_default_env_vars(env_vars)

    def _set_default_env_vars(self, env_vars):
        # Set default values if not provided
        if not env_vars.get("TMPDIR"):
            env_vars["TMPDIR"] = "/tmp"

        if not env_vars.get("APP_DIR"):
            if self.build_env_vars.get("APP_NAME"):
                env_vars["APP_DIR"] = f"var/tmp/{self.build_env_vars['APP_NAME']}"
            else:
                env_vars["APP_DIR"] = "var/tmp/terraform"

        return env_vars

    def _get_timeout(self):
        try:
            timeout = int(self.build_timeout)
            self.logger.debug(f"_get_timeout - using user specified timeout {timeout}s")
        except (ValueError, TypeError):
            self.logger.debug("_get_timeout - using default of 800s")
            timeout = self.MAX_LAMBDA_TIMEOUT

        if timeout > self.MAX_LAMBDA_TIMEOUT:
            self.logger.debug(f"_get_timeout - timeout of {timeout} exceeds limit of {self.MAX_LAMBDA_TIMEOUT}s for lambda -> resetting to {self.MAX_LAMBDA_TIMEOUT}s")
            timeout = self.MAX_LAMBDA_TIMEOUT

        return timeout

    def get_base_event(self):
        self.build_timeout = self._get_timeout()
        self.build_expire_at = time() + self.build_timeout

        # Define the configuration for invoking the Lambda function
        env_vars = self._env_vars_to_lambda_format()
        timeout = max(1, int(self.build_timeout/60))

        self.logger.debug("#" * 32)
        self.logger.debug("# ref 324523453 env vars for lambda build")
        self.logger.json(env_vars)
        self.logger.debug("#" * 32)

        return {
            "lambda_function_name": self.lambda_function_name,
            "payload": json.dumps({
                "cmds_b64": self.cmds_b64,
                "env_vars_b64": b64_encode(env_vars),
            }),
            "expiry_minutes": timeout
        }
