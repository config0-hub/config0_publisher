#!/usr/bin/env python

import re
import json
from time import sleep
from time import time
#import gzip
#import traceback
#from io import BytesIO

from config0_publisher.serialization import b64_encode
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

        self.lambda_client = self.session.client('lambda')
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

    #def _get_build_status(self):

    #    response = self.lambda_client.get_invocation(
    #        FunctionName=self.lambda_function_name,
    #        InvocationId=self.request_id
    #    )

    #    status_code = response['StatusCode']
    #    print("Status Code:",status_code)
    #    status = response['Status']

    #    return {self.request_id: {"status": status}}

    #def _set_build_status(self):
    #
    #    # Extract the status from the response
    #    self.results["build_status"] = self._get_build_status()[self.request_id]["status"]

    def _check_status(self):
        '''
        'InProgress': The invocation is still in progress.
        'Success': The invocation finished successfully.
        'Failed': The invocation failed.
        '''

        #self._set_build_status()

        status = self.results["build_status"]

        if status == 'IN_PROGRESS':
            self.logger.debug(f"lambda status: {status}")
            return

        done = [ "Success",
                 "Failed" ]

        if status in done:
            self.logger.debug(f"lambda completed with status: {status}")
            return status

        self.logger.debug(f"lambda status: {status}")

        return status

    def _set_build_status_codes(self):

        build_status = self.results["build_status"]

        if build_status == 'Success':
            self.results["status_code"] = "successful"
            self.results["status"] = True
            return True

        failed_message = f"lambda failed with status {build_status}"

        if build_status == 'Failed':
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "failed"
            self.results["status"] = False
            return True

        _time_elapsed = int(time()) - self.results["run_t0"]

        # if run time exceed 5 minutes, then it
        # will be considered failed
        if _time_elapsed > 300:
            failed_message = "build should match one of the build status: after 300 seconds"
            self.logger.error(failed_message)
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "failed"
            self.results["status"] = False
            return False

        return

    def _eval_build(self):

        _t1 = int(time())
        status = None

        while True:

            sleep(5)

            _time_elapsed = _t1 - self.results["run_t0"]

            if _time_elapsed > self.build_timeout:
                failed_message = "run max time exceeded {}".format(self.build_timeout)
                self.phase_result["logs"].append(failed_message)
                self.results["failed_message"] = failed_message
                self.results["status"] = False
                self.logger.warn(failed_message)
                status = False
                break

            # check build exceeded total build time alloted
            if _t1 > self.build_expire_at:
                self.results["status_code"] = "timed_out"
                self.results["status"] = False
                failed_message = "build timed out: after {} seconds.".format(str(self.build_timeout))
                self.phase_result["logs"].append(failed_message)
                self.results["failed_message"] = failed_message
                self.logger.warn(failed_message)
                status = False
                break

            self._get_log()

        self.results["time_elapsed"] = int(time()) - self.results["run_t0"]

        if not self.output:
            self.output = 'Could not get log request_id "{}"'.format(self.request_id)

        return status
    def _get_log(self):

        if self.output:
            return {"status":True}

        log_group_name = f'/aws/lambda/{self.lambda_function_name}'

        self.logs_client = self.session.client('logs')

        # Filter the log events based on the request ID
        response = self.logs_client.filter_log_events(
            logGroupName=log_group_name,
            filterPattern=self.request_id,
        )

        # Retrieve the log events from the response
        log_events = response['events']

        _logs = []

        # Print the log messages
        for event in log_events:
            message = event.get('message')
            if not message:
                continue
            _logs.append(message)
            print('-- Log Message:', message)

        self.output = "\n".join(_logs)

        return {"status":True}

    def _set_build_summary(self):

        if self.results["status_code"] == "successful":
            summary_msg = "# Successful \n# request_id {}".format(self.request_id)

        elif self.results["status_code"] == "timed_out":
            summary_msg = "# Timed out \n# request_id {}".format(self.request_id)

        elif self.request_id is False:
            self.results["status_code"] = "failed"
            summary_msg = "# Never Triggered"

        elif self.request_id:
            self.results["status_code"] = "failed"
            summary_msg = "# Failed \n# request_id {}".format(self.request_id)

        else:
            self.results["status_code"] = "failed"
            summary_msg = "# Failed \n# request_id {}".format(self.request_id)

        self.results["msg"] = summary_msg

        return summary_msg

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

        # Invoke the Lambda function with the specified environment variables
        self.response = self.lambda_client.invoke(**invocation_config)

        self.request_id = self.response['ResponseMetadata']['RequestId']
        self.logger.debug_highlight(f"Lambda function invocation request ID: {self.request_id}")

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

    def check(self,wait_int=10,retries=12):

        self._set_build_status()

        for retry in range(retries):
            self.logger.debug(f'check: lambda function "{self.lambda_function_name}" request_id "{self.request_id}" retry {retry}/{retries} {wait_int} seconds')
            if self._check_status():
                return True
            sleep(wait_int)
        return

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

        if not self.check(wait_int=wait_int,
                          retries=retries):
            return

        return self._retrieve()

    def _retrieve(self):

        self._eval_build()
        self.phase_result["executed"].append("eval_build")

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
        self._retrieve()

        return self.results