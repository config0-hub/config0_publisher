#!/usr/bin/env python

import re
import json
import botocore
from time import sleep
from time import time

#import gzip
#import traceback
#from io import BytesIO

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
                      "AWS_SECRET_ACCESS_KEY" ]

        sparse_keys = [ "STATEFUL_ID",
                        "REMOTE_STATEFUL_BUCKET",
                        "TMPDIR",
                        "APP_DIR" ]

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

        try:
            timeout = int(self.build_timeout)
        except:
            timeout = 900

        if timeout > 900:
            timeout = 900

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

        self.response = self.lambda_client.invoke(**invocation_config)

        #self.request_id = self.response['ResponseMetadata']['RequestId']
        #self.logger.debug_highlight(f"Lambda function invocation request ID: {self.request_id}")
        #self.logger.debug("a"*32)
        #self.logger.debug_highlight(self.response)
        #self.logger.debug(self.response.keys())

        # ['ResponseMetadata', 'StatusCode', 'LogResult', 'ExecutedVersion', 'Payload']

        self.logger.debug("b"*32)
        self.logger.debug("b"*32)
        log_result = b64_decode(self.response["LogResult"])
        status = self.response["StatusCode"]
        self.logger.debug("c"*32)
        self.logger.debug(f"status = {status}")
        self.logger.debug("d"*32)
        self.logger.debug(f"log_result = \n{log_result}")
        self.logger.debug("e"*32)

    def _submit(self):

        self.phase_result = self.new_phase("submit")

        # we don't want to clobber the intact
        # stateful files from creation
        if self.method != "destroy":
            self.upload_to_s3_stateful()

        self.phase_result["executed"].append("upload_to_s3")

        self._trigger_build()
        self.phase_result["executed"].append("trigger_build")
        self.phase_result["status"] = True
        self.results["phases_info"].append(self.phase_result)

        return self.results

    # revisit
    # testtest456
    # check with endpoint?
    #def check(self,wait_int=10,retries=12):

    #    for retry in range(retries):
    #        self.logger.debug(f'check: lambda function "{self.lambda_function_name}" request_id "{self.request_id}" retry {retry}/{retries} {wait_int} seconds')
    #        if self._check_status():
    #            return True
    #        sleep(wait_int)
    #    return

    def retrieve(self,**kwargs):

        '''
        {
          "inputargs": {
              "interval": 10,
              "retries": 12
          },
              "name": "retrieve",
              "timewait": 3
        }

        retrieve is the same as _retrieve except
        there is a check of the build status
        where the check itself times out
        '''

        self.phase_result = self.new_phase("retrieve")

        wait_int = kwargs.get("interval",10)
        retries = kwargs.get("retries",12)

        #if not self.check(wait_int=wait_int,
        #                  retries=retries):
        #    return

        return self._retrieve()

    def _retrieve(self):

        self.s3_stateful_to_share_dir()
        self.phase_result["executed"].append("s3_share_dir")

        self.clean_output()

        if self.output:
            self.results["output"] = self.output

        self.print_output()

        if self.results.get("failed_message"):
            self.logger.error(self.results["failed_message"])
            raise Exception(self.results.get("failed_message"))

        self.phase_result["status"] = True
        self.results["phases_info"].append(self.phase_result)

        return self.results

    # this is a single run and not in phases
    # we use _retrieve instead of retrieve method
    def run(self):

        self._submit()

        # testtest456
        #exit(0)
        #raise Exception('yoyo')
        #self._retrieve()

        return self.results