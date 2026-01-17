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
        if not _build:
            return

        self.logarn = _build["logarn"]
        self.results["build_status"] = _build["status"]
        self.results["inputargs"]["logarn"] = self.logarn

    def _check_build_status(self):
        _build = self._get_build_status([self.build_id])[self.build_id]
        if not _build:
            return

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

        while True:
            sleep(5)

            # Check build status explicitly - returns None if IN_PROGRESS, or status string if done
            build_status_result = self._check_build_status()
            
            # If build is done (not None), break the loop immediately
            # Key insight: If _check_build_status() returns non-None, the build is DONE
            # We break as soon as we detect completion, regardless of _set_build_status_codes() return value
            if build_status_result is not None:
                # Build is complete - set status codes (for side effects) then break
                # This ensures proper status codes are set even if _set_build_status_codes() returns None
                status_codes_result = self._set_build_status_codes()
                
                # If status codes weren't processed (unexpected status), log warning but still break
                if status_codes_result is None:
                    self.logger.warn(f"Build completed with unexpected status: {build_status_result}, status codes not processed")
                    # Set default failure status if not already set
                    if "status" not in self.results or self.results.get("status") is None:
                        self.results["status"] = False
                        self.results["failed_message"] = f"Build completed with status {build_status_result} but status codes not processed"
                
                # Use the status set by _set_build_status_codes() or fallback to False for unknown statuses
                status = self.results.get("status", False)
                self.logger.debug(f"Build completed with status: {self.results.get('build_status')}, exit status: {status}")
                break

            # Update current time for elapsed time calculations (inside loop for accuracy)
            _t1 = int(time())
            _time_elapsed = _t1 - self.results["run_t0"]

            if _time_elapsed > self.build_timeout:
                failed_message = f"run max time exceeded {self.build_timeout}"
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
        maxtime = 90  # Increased from 30 to 90 seconds to allow time for CodeBuild to write logs after STOPPED/ABORTED
        t0 = int(time())

        while True:
            _time_elapsed = int(time()) - t0

            if _time_elapsed > maxtime:
                self.logger.debug(f"time expired to retrieved log {_time_elapsed} seconds")
                return False

            results = self._set_log(build_id_suffix)

            if results.get("status") is True:
                return True

            # Don't exit early on errors - keep retrying until timeout
            # CodeBuild writes logs asynchronously, so NoSuchKey errors are expected initially
            # for STOPPED/ABORTED builds. Log the warning but continue retrying.
            if results.get("status") is False and results.get("failed_message"):
                self.logger.debug(f"Log not yet available (attempt {int(_time_elapsed/2) + 1}): {results.get('failed_message', '')[:100]}")

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
        build_env_vars = self.build_env_vars.copy()
        build_env_vars["OUTPUT_BUCKET"] = self.tmp_bucket
        build_env_vars["EXECUTION_ID"] = self.execution_id
        build_env_vars["OUTPUT_BUCKET_KEY"] = self.execution_id_path
        build_env_vars["BUILD_EXPIRE_AT"] = str(int(self.build_expire_at))

        for _k, _v in build_env_vars.items():
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

        return new_build

    def pre_trigger(self, sparse_env_vars=True):

        # we don't want to clobber the intact
        # stateful files from creation
        if self.method == "create":
            self.upload_to_s3_stateful()

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
        self.s3_stateful_to_share_dir()
        self.clean_output()

        if self.output:
            self.results["output"] = self._concat_log()

        return self.results

    def run(self, sparse_env_vars=True):

        self.trigger_build(sparse_env_vars=sparse_env_vars)
        self._retrieve()

        # testtest456
        if not self.results.get("status"):
            exit(9)

        exit(0)

        return self.results
