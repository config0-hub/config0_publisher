#!/usr/bin/env python

"""
CodebuildResourceHelper: AWS CodeBuild project and build management.

This class manages AWS CodeBuild operations including:

Attributes:
    buildspec (str): BuildSpec for CodeBuild project
    build_id (str): Current build ID
    project_name (str): CodeBuild project name
    build_timeout (int): Maximum build time in seconds
    build_expire_at (int): Timestamp when build expires
    logarn (str): CloudWatch log ARN

Environment Variables:
    AWS_DEFAULT_REGION: AWS region for CodeBuild
    CODEBUILD_BUILD_IMAGE: Docker image for builds
    CODEBUILD_COMPUTE_TYPE: Compute resources for builds
"""

import os
import re
import gzip
import traceback
from io import BytesIO
from time import sleep, time
from config0_publisher.cloud.aws.common import AWSCommonConn

class CodebuildResourceHelper(AWSCommonConn):
    DEFAULT_CONFIG = {
        "build_image": "aws/codebuild/standard:7.0",
        "image_type": "LINUX_CONTAINER",
        "compute_type": "BUILD_GENERAL1_SMALL",
        "codebuild_basename": "config0-iac"
    }

    ENV_VARS = {
        "tmp_bucket": True,
        "log_bucket": True,
        "build_image": True,
        "image_type": True,
        "compute_type": True,
        "codebuild_basename": True,
        "app_dir": None,
        "stateful_id": None,
        "remote_stateful_bucket": None,
        "run_share_dir": None,
        "share_dir": None
    }

    SKIP_KEYS = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
    SPARSE_KEYS = ["STATEFUL_ID", "REMOTE_STATEFUL_BUCKET", "TMPDIR", "APP_DIR", "SSM_NAME"]

    def __init__(self, **kwargs):
        self.buildspec = kwargs.get("buildspec")
        self.build_id = None
        self.project_name = os.environ.get("CODEBUILD_PROJECT", "config0-iac")
        self.logarn = None

        if "set_env_vars" in kwargs:
            kwargs["set_env_vars"] = self.ENV_VARS

        AWSCommonConn.__init__(self,
                               default_values=self.DEFAULT_CONFIG,
                               **kwargs)

        self.phase_result = {}

        # codebuild specific settings and variables
        self.codebuild_client = self.session.client('codebuild')

        if not self.results["inputargs"].get("build_image"):
            self.results["inputargs"]["build_image"] = self.build_image

        if not self.results["inputargs"].get("image_type"):
            self.results["inputargs"]["image_type"] = self.image_type

        if not self.results["inputargs"].get("compute_type"):
            self.results["inputargs"]["compute_type"] = self.compute_type

        if not self.results["inputargs"].get("codebuild_basename"):
            self.results["inputargs"]["codebuild_basename"] = self.codebuild_basename

    def _get_build_status(self, build_ids):
        results = {}

        builds = self.codebuild_client.batch_get_builds(ids=build_ids)['builds']

        for build in builds:
            results[build["id"]] = {"status": build["buildStatus"],
                                   "logarn": build["logs"]["s3LogsArn"]}

        return results

    def _set_current_build(self):
        _build = self._get_build_status([self.build_id])[self.build_id]
        self.logarn = _build["logarn"]

        self.results["build_status"] = _build["status"]
        self.results["inputargs"]["logarn"] = self.logarn

    def _check_build_status(self):
        _build = self._get_build_status([self.build_id])[self.build_id]

        build_status = _build["status"]
        self.results["build_status"] = build_status

        self.logger.debug(f"codebuild status: {build_status}")

        if build_status == 'IN_PROGRESS':
            return

        done = ["SUCCEEDED",
                "STOPPED",
                "TIMED_OUT",
                "FAILED_WITH_ABORT",
                "FAILED",
                "FAULT"]

        if build_status in done:
            return build_status

    def _set_build_status_codes(self):
        build_status = self.results["build_status"]

        if build_status == 'SUCCEEDED':
            self.results["status_code"] = "successful"
            self.results["status"] = True
            return True

        failed_message = f"codebuild failed with build status {build_status}"

        if build_status == 'FAILED':
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "failed"
            self.results["status"] = False
            return True

        if build_status == 'FAULT':
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "failed"
            self.results["status"] = False
            return True

        if build_status == 'STOPPED':
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "failed"
            self.results["status"] = False
            return True

        if build_status == 'TIMED_OUT':
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "timed_out"
            self.results["status"] = False
            return True

        if build_status == 'FAILED_WITH_ABORT':
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
        self._set_current_build()

        _t1 = int(time())

        while True:
            sleep(5)

            if self._check_build_status() and self._set_build_status_codes():
                status = True
                break

            _time_elapsed = _t1 - self.results["run_t0"]

            if _time_elapsed > self.build_timeout:
                failed_message = f"run max time exceeded {self.build_timeout}"
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
                failed_message = f"build timed out: after {str(self.build_timeout)} seconds."
                self.phase_result["logs"].append(failed_message)
                self.results["failed_message"] = failed_message
                self.logger.warn(failed_message)
                status = False
                break

        self.wait_for_log()
        self.results["time_elapsed"] = int(time()) - self.results["run_t0"]

        if not self.output:
            self.output = f'Could not get log build_id "{self.build_id}"'

        return status

    def wait_for_log(self):
        build_id_suffix = self.build_id.split(":")[1]
        maxtime = 30
        t0 = int(time())

        while True:
            _time_elapsed = int(time()) - t0

            if _time_elapsed > maxtime:
                self.logger.debug(f"time expired to retrieved log {_time_elapsed} seconds")
                return False

            results = self._set_log(build_id_suffix)

            if results.get("status") is True:
                return True

            if results.get("status") is False and results.get("failed_message"):
                self.logger.warn(results["failed_message"])
                return False

            sleep(2)

    def _set_log(self, build_id_suffix):
        if self.output:
            return {"status": True}

        if self.logarn:
            _log_elements = self.logarn.split("/codebuild/logs/")
            _logname = f"codebuild/logs/{_log_elements[1]}"
            _log_bucket = _log_elements[0].split("arn:aws:s3:::")[1]
        else:
            _logname = f"codebuild/logs/{build_id_suffix}.gz"
            _log_bucket = self.log_bucket

        _dstfile = f'/tmp/{build_id_suffix}.gz'

        try:
            obj = self.s3.Object(_log_bucket,
                                _logname)

            _read = obj.get()['Body'].read()
        except:
            msg = traceback.format_exc()
            failed_message = f"failed to get log: s3://{_log_bucket}/{_logname}\n\nstacktrace:\n\n{msg}"
            return {"status": False,
                    "failed_message": failed_message}

        self.logger.debug(f"retrieved log: s3://{_log_bucket}/{_logname}")
        gzipfile = BytesIO(_read)
        gzipfile = gzip.GzipFile(fileobj=gzipfile)
        log = gzipfile.read().decode('utf-8')
        self.output = log

        return {"status": True}

    def _set_build_summary(self):
        if self.results["status_code"] == "successful":
            summary_msg = f"# Successful \n# build_id {self.build_id}"
        elif self.results["status_code"] == "timed_out":
            summary_msg = f"# Timed out \n# build_id {self.build_id}"
        elif self.build_id is False:
            self.results["status_code"] = "failed"
            summary_msg = "# Never Triggered"
        elif self.build_id:
            self.results["status_code"] = "failed"
            summary_msg = f"# Failed \n# build_id {self.build_id}"
        else:
            self.results["status_code"] = "failed"
            summary_msg = "# Never Triggered"

        self.results["msg"] = summary_msg

        return summary_msg

    def _env_vars_to_codebuild_format(self, sparse=True):
        env_vars = [] 
        _added = [] 
        if not self.build_env_vars:
            return env_vars

        pattern = r"^CODEBUILD"

        for _k, _v in self.build_env_vars.items():
            if not _v:
                self.logger.debug(f"env var {_k} is empty/None - skipping")
                continue

            if _k in self.SKIP_KEYS:
                continue

            if sparse and _k not in self.SPARSE_KEYS:
                continue

            if re.search(pattern, _k):
                continue

            # cannot duplicate env vars
            if _k in _added:
                continue

            _added.append(_k)

            _env_var = {'name': _k,
                         'value': _v,
                         'type': 'PLAINTEXT'}

            env_vars.append(_env_var)

        _env_var = {'name': "OUTPUT_BUCKET",
                    'value': self.tmp_bucket,
                    'type': 'PLAINTEXT'}

        env_vars.append(_env_var)

        _env_var = {'name': "EXECUTION_ID",
                    'value': self.execution_id,
                    'type': 'PLAINTEXT'}

        env_vars.append(_env_var)

        _env_var = {'name': "OUTPUT_BUCKET_KEY",
                    'value': self.execution_id_path,
                    'type': 'PLAINTEXT'}

        env_vars.append(_env_var)

        _env_var = {'name': "BUILD_EXPIRE_AT",
                    'value': str(int(self.build_expire_at)),
                    'type': 'PLAINTEXT'}

        return env_vars

    def trigger_build(self, sparse_env_vars=True):

        inputargs = self.get_trigger_inputargs(sparse_env_vars=sparse_env_vars)
        project_name = inputargs["projectName"]
        new_build = self.codebuild_client.start_build(**inputargs)

        self.build_id = new_build['build']['id']
        self.results["inputargs"]["build_id"] = self.build_id
        self.results["inputargs"]["project_name"] = project_name

        _log = f"trigger run on codebuild project: {project_name}, build_id: {self.build_id}, build_expire_at: {self.build_expire_at}"
        self.logger.debug(_log)
        self.phase_result["logs"].append(_log)

        return new_build

    def pre_trigger(self, sparse_env_vars=True):

        self.phase_result = self.new_phase("submit")

        # we don't want to clobber the intact
        # stateful files from creation
        if self.method == "create":
            self.upload_to_s3_stateful()
            self.phase_result["executed"].append("upload_to_s3")

        return self.get_trigger_inputargs(sparse_env_vars=sparse_env_vars)

    def get_trigger_inputargs(self, sparse_env_vars=True):

        timeout = max(1, int(self.build_timeout/60))
        self.logger.debug_highlight(f"running job on codebuild project {self.project_name}")
        env_vars_codebuild_format = self._env_vars_to_codebuild_format(sparse=sparse_env_vars)
        inputargs = {"projectName": self.project_name,
                     "environmentVariablesOverride": env_vars_codebuild_format,
                     "timeoutInMinutesOverride": timeout,
                     "imageOverride": self.build_image,
                     "computeTypeOverride": self.compute_type,
                     "environmentTypeOverride": self.image_type}
        if self.buildspec:
            inputargs["buildspecOverride"] = self.buildspec
        return inputargs

    def _submit(self, sparse_env_vars=True):

        self.phase_result["executed"].append("trigger_codebuild")
        self.phase_result["status"] = True
        self.results["phases_info"].append(self.phase_result)

        return self.results

    def check(self, wait_int=10, retries=12):
        self._set_current_build()

        for retry in range(retries):
            self.logger.debug(f'check: codebuild_project_name "{self.project_name}" codebuild_id "{self.build_id}" retry {retry}/{retries} {wait_int} seconds')
            if self._check_build_status():
                return True
            sleep(wait_int)

        return

    def retrieve(self, build_id=None):

        if build_id:
            self.build_id = build_id

        return self._retrieve()

    def _concat_log(self):
        try:
            _output = self.download_log_from_s3()
        except:
            _output = None

        if not _output:
            return "\n".join(self.output)

        return _output + '\n' + "\n".join(self.output)

    def _retrieve(self):
        self._eval_build()
        self.phase_result["executed"].append("eval_build")

        if self.s3_stateful_to_share_dir():
            self.phase_result["executed"].append("s3_share_dir")

        self.clean_output()

        if self.output:
            self.results["output"] = self._concat_log()

        self.phase_result["status"] = True
        self.results["phases_info"].append(self.phase_result)

        return self.results

    # this is a single run and not in phases
    # we use _retrieve instead of retrieve method
    def run(self, sparse_env_vars=True):
        self._submit(sparse_env_vars=sparse_env_vars)
        self._retrieve()

        return self.results
