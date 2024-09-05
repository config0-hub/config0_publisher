#!/usr/bin/env python

import re
import json
from time import time

from config0_publisher.serialization import b64_encode
from config0_publisher.serialization import b64_decode
from config0_publisher.cloud.aws.common import AWSCommonConn
#from config0_publisher.utilities import print_json

class LambdaResourceHelper(AWSCommonConn):

    def __init__(self,**kwargs):

        default_values = {
            "lambda_function_name":"config0-iac"
        }

        AWSCommonConn.__init__(self,
                               default_values=default_values,
                               set_env_vars=self.get_set_env_vars(),
                               **kwargs)

        self.init_env_vars = kwargs.get("init_env_vars")
        self.cmds_b64 = b64_encode(kwargs["cmds"])

        #self.lambda_client = self.session.client('lambda')

        self.logs_client = self.session.client('logs')

        if not self.results["inputargs"].get("lambda_function_name"):
            self.results["inputargs"]["lambda_function_name"] = self.lambda_function_name

    def get_set_env_vars(self):

        return {
            "tmp_bucket":True,
            "log_bucket":True,
            "app_dir":None,
            "stateful_id":None,
            "remote_stateful_bucket":None,
            "lambda_function_name":None,
            "run_share_dir":None,
            "share_dir":None
        }

    def _env_vars_to_lambda_format(self,sparse=True):

        skip_keys = [ "AWS_ACCESS_KEY_ID",
                      "AWS_SECRET_ACCESS_KEY",
                      "AWS_SESSION_TOKEN" ]

        sparse_keys = [ "STATEFUL_ID",
                        "REMOTE_STATEFUL_BUCKET",
                        "TMPDIR",
                        "APP_DIR",
                        "SSM_NAME" ]

        if self.init_env_vars:
            env_vars = self.init_env_vars
        else:
            env_vars = {}

        _added = []

        if not self.build_env_vars:
            return env_vars
        pattern = r"^AWS_LAMBDA_"

        for _k,_v in self.build_env_vars.items():

            if not _v:
                self.logger.debug("env var {} is empty/None - skipping".format(_k))
                continue

            if _k in skip_keys:
                continue

            if sparse and _k not in sparse_keys:
                continue

            if re.search(pattern, _k):
                continue

            # cannot duplicate env vars
            if _k in _added:
                continue

            _added.append(_k)

            env_vars[_k] = _v

        return env_vars
    def _trigger_build(self):

        # we limit the build to 500 seconds, which is one min
        # less than 10 minutes
        try:
            timeout = int(self.build_timeout)
        except:
            timeout = 500

        if timeout > 500:
            timeout = 500

        self.build_expire_at = time() + timeout

        # Define the configuration for invoking the Lambda function
        invocation_config = {
            'FunctionName': self.lambda_function_name,
            'InvocationType': 'RequestResponse',
            'LogType':'Tail',
            'Payload': json.dumps(
                {
                    "cmds_b64":self.cmds_b64,
                    "env_vars_b64":b64_encode(self._env_vars_to_lambda_format()),
                })
        }

        return self.lambda_client.invoke(**invocation_config)

    def _submit(self):

        self.phase_result = self.new_phase("submit")

        # we don't want to clobber the intact
        # stateful files from creation
        if self.method == "create":
            self.upload_to_s3_stateful()

        # ['ResponseMetadata', 'StatusCode', 'LogResult', 'ExecutedVersion', 'Payload']
        self.response = self._trigger_build()

        lambda_status = int(self.response["StatusCode"])

        payload = json.loads(self.response["Payload"].read().decode())

        self.results["lambda_status"] = lambda_status

        try:
            lambda_results = json.loads(payload["body"])
        except:
            lambda_results = json.loads(payload)
            lambda_results["status"] = False
            self.results["failed_message"] = " ".join(lambda_results["stackTrace"])
            self.results["output"] = " ".join(lambda_results["stackTrace"])
            #self.results["failed_message"] = lambda_results["errorMessage"]
            #self.results["stack_trace"] = lambda_results["stackTrace"]

        self.results["lambda_results"] = lambda_results

        if lambda_results["status"] is True and lambda_status == 200:
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

        if not self.results.get("output"):
            self.results["output"] = b64_decode(self.response["LogResult"])

        return self.results

    def run(self):

        self._submit()

        if self.results.get("status") is False and self.method == "validate":
            self.results["failed_message"] = "the resources have drifted"
        elif self.results.get("status") is False and self.method == "create":
            self.results["failed_message"] = "creation of resources have failed"
        elif self.results.get("status") is False and self.method == "destroy":
            self.results["failed_message"] = "destroying of resources have failed"

        return self.results