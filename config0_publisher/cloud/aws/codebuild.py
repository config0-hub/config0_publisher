#!/usr/bin/env python

"""
CodebuildResourceHelper: AWS CodeBuild project and build management.
"""

import re
import gzip
import traceback
from io import BytesIO
from time import sleep, time
from config0_publisher.cloud.aws.common import AWSCommonConn


class CodebuildResourceHelper(AWSCommonConn):
    """Manages AWS CodeBuild operations including project creation and build management."""
    
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
        """Initialize CodeBuild resource helper with buildspec and AWS connection."""
        self.buildspec = kwargs.get("buildspec")
        self.build_id = None
        self.project_name = None
        self.logarn = None
        self.output = None

        if "set_env_vars" in kwargs:
            kwargs["set_env_vars"] = self.ENV_VARS

        AWSCommonConn.__init__(self,
                               default_values=self.DEFAULT_CONFIG,
                               **kwargs)

        # codebuild specific settings and variables
        try:
            self.codebuild_client = self.session.client('codebuild')
        except Exception as e:
            self.logger.error(f"Failed to create CodeBuild client: {str(e)}")
            raise

        # Set default values if not provided in inputargs
        for key in ["build_image", "image_type", "compute_type", "codebuild_basename"]:
            if not self.results["inputargs"].get(key):
                self.results["inputargs"][key] = getattr(self, key)

    def _get_build_status(self, build_ids):
        """Get status of one or more builds by their IDs."""
        results = {}
        
        try:
            builds = self.codebuild_client.batch_get_builds(ids=build_ids)['builds']
            
            for build in builds:
                results[build["id"]] = {
                    "status": build["buildStatus"],
                    "logarn": build["logs"]["s3LogsArn"]
                }
        except Exception as e:
            self.logger.error(f"Failed to get build status: {str(e)}")
            
        return results

    def _set_current_build(self):
        """Set current build status and log ARN."""
        try:
            _build = self._get_build_status([self.build_id])[self.build_id]
            self.logarn = _build["logarn"]

            self.results["build_status"] = _build["status"]
            self.results["inputargs"]["logarn"] = self.logarn
        except Exception as e:
            self.logger.error(f"Failed to set current build: {str(e)}")
            raise

    def _check_build_status(self):
        """Check status of current build and return if completed."""
        try:
            _build = self._get_build_status([self.build_id])[self.build_id]
            
            build_status = _build["status"]
            self.results["build_status"] = build_status

            self.logger.debug(f"codebuild status: {build_status}")

            if build_status == 'IN_PROGRESS':
                return None

            done = ["SUCCEEDED", "STOPPED", "TIMED_OUT", 
                    "FAILED_WITH_ABORT", "FAILED", "FAULT"]

            if build_status in done:
                return build_status
            
            return None
        except Exception as e:
            self.logger.error(f"Failed to check build status: {str(e)}")
            return None

    def _set_build_status_codes(self):
        """Set status codes based on current build status."""
        build_status = self.results["build_status"]

        if build_status == 'SUCCEEDED':
            self.results["status_code"] = "successful"
            self.results["status"] = True
            return True

        failed_message = f"codebuild failed with build status {build_status}"

        if build_status in ['FAILED', 'FAULT', 'STOPPED', 'FAILED_WITH_ABORT']:
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "failed"
            self.results["status"] = False
            return True

        if build_status == 'TIMED_OUT':
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "timed_out"
            self.results["status"] = False
            return True

        _time_elapsed = int(time()) - self.results["run_t0"]

        # if run time exceed 5 minutes, then it will be considered failed
        if _time_elapsed > 300:
            failed_message = "build should match one of the build status: after 300 seconds"
            self.logger.error(failed_message)
            self.results["failed_message"] = failed_message
            self.results["status_code"] = "failed"
            self.results["status"] = False
            return False

        return None

    def _eval_build(self):
        """Evaluate build status until completion or timeout."""
        try:
            self._set_current_build()
            
            _t1 = int(time())

            while True:
                sleep(5)

                build_status = self._check_build_status()
                if build_status and self._set_build_status_codes():
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
        except Exception as e:
            self.logger.error(f"Error evaluating build: {str(e)}")
            self.results["failed_message"] = f"Error evaluating build: {str(e)}"
            self.results["status"] = False
            return False

    def wait_for_log(self):
        """Wait for build logs to become available."""
        try:
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
        except Exception as e:
            self.logger.error(f"Error waiting for log: {str(e)}")
            return False

    def _set_log(self, build_id_suffix):
        """Retrieve and set build logs from S3."""
        if self.output:
            return {"status": True}

        try:
            if self.logarn:
                _log_elements = self.logarn.split("/codebuild/logs/")
                _logname = f"codebuild/logs/{_log_elements[1]}"
                _log_bucket = _log_elements[0].split("arn:aws:s3:::")[1]
            else:
                _logname = f"codebuild/logs/{build_id_suffix}.gz"
                _log_bucket = self.log_bucket

            _dstfile = f'/tmp/{build_id_suffix}.gz'

            try:
                obj = self.s3.Object(_log_bucket, _logname)
                _read = obj.get()['Body'].read()
            except Exception as e:
                msg = traceback.format_exc()
                failed_message = f"failed to get log: s3://{_log_bucket}/{_logname}\n\nstacktrace:\n\n{msg}"
                return {"status": False, "failed_message": failed_message}

            self.logger.debug(f"retrieved log: s3://{_log_bucket}/{_logname}")
            gzipfile = BytesIO(_read)
            gzipfile = gzip.GzipFile(fileobj=gzipfile)
            log = gzipfile.read().decode('utf-8')
            self.output = log

            return {"status": True}
        except Exception as e:
            failed_message = f"Error setting log: {str(e)}"
            return {"status": False, "failed_message": failed_message}

    def _set_build_summary(self):
        """Generate summary message based on build status."""
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
        """Convert environment variables to CodeBuild format."""
        env_vars = [] 
        _added = []
        
        if not hasattr(self, 'build_env_vars') or not self.build_env_vars:
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

            _env_var = {
                'name': _k,
                'value': _v,
                'type': 'PLAINTEXT'
            }

            env_vars.append(_env_var)

        # Always add output bucket information
        env_vars.extend([
            {
                'name': "OUTPUT_BUCKET",
                'value': self.tmp_bucket,
                'type': 'PLAINTEXT'
            },
            {
                'name': "OUTPUT_BUCKET_KEY",
                'value': self.s3_output_key,
                'type': 'PLAINTEXT'
            },
            {
                'name': "BUILD_EXPIRE_AT",
                'value': str(int(self.build_expire_at)),
                'type': 'PLAINTEXT'
            }
        ])

        return env_vars

    def get_available_projects(self, max_queue_size=5):
        """Get available CodeBuild projects with their current build counts."""
        try:
            response = self.codebuild_client.list_projects()
            projects = [p for p in response['projects'] if self.codebuild_basename in p]
            results = {}
            
            for project in projects:
                self.logger.debug(f"evaluating codebuild project {project}")

                try:
                    response = self.codebuild_client.list_builds_for_project(
                        projectName=project,
                        sortOrder='ASCENDING'
                    )

                    if not response["ids"]:
                        results[project] = 0
                        continue

                    build_statues = self._get_build_status(response["ids"])
                    current_build_ids = []

                    for build_id, build_info in build_statues.items():
                        if build_info["status"] == "IN_PROGRESS":
                            current_build_ids.append(build_id)

                    build_count = len(current_build_ids)
                    self.logger.debug(f"Project: {project}, Build Count: {build_count}")

                    if build_count < max_queue_size:
                        results[project] = build_count
                except Exception as e:
                    self.logger.warn(f"Error checking project {project}: {str(e)}")
                    continue

            if not results:
                return None

            return sorted(results, key=lambda x: results[x])
        except Exception as e:
            self.logger.error(f"Error getting available projects: {str(e)}")
            return None

    def _get_codebuild_projects(self, sleep_int=10):
        """Get available CodeBuild projects with retries."""
        for retry in range(3):
            try:
                empty_queue_projects = self.get_available_projects()
                if empty_queue_projects:
                    return empty_queue_projects
            except Exception as e:
                self.logger.warn(f"Error getting CodeBuild projects (retry {retry+1}/3): {str(e)}")
                empty_queue_projects = None
                
            sleep(sleep_int)

        return None

    def trigger_build(self, sparse_env_vars=True):
        """Trigger a new CodeBuild build."""
        try:
            projects = self.get_available_projects()
            self.project_name = None

            if not projects:
                self.logger.warn(f"Cannot find matching project - using codebuild_basename {self.codebuild_basename}")
                projects = [self.codebuild_basename]

            timeout = max(1, int(self.build_timeout/60))

            for project_name in projects:
                self.logger.debug_highlight(f"running job on codebuild project {project_name}")

                env_vars_codebuild_format = self._env_vars_to_codebuild_format(sparse=sparse_env_vars)

                inputargs = {
                    "projectName": project_name,
                    "environmentVariablesOverride": env_vars_codebuild_format,
                    "timeoutInMinutesOverride": timeout,
                    "imageOverride": self.build_image,
                    "computeTypeOverride": self.compute_type,
                    "environmentTypeOverride": self.image_type
                }

                if self.buildspec:
                    inputargs["buildspecOverride"] = self.buildspec

                try:
                    new_build = self.codebuild_client.start_build(**inputargs)
                    self.project_name = project_name
                    break
                except Exception as e:
                    msg = traceback.format_exc()
                    self.logger.warn(f"Could not start build on codebuild {project_name}\n\n{msg}")
                    continue

            if not self.project_name:
                raise Exception("Could not trigger codebuild execution")

            self.build_id = new_build['build']['id']
            self.results["inputargs"]["build_id"] = self.build_id
            self.results["inputargs"]["project_name"] = project_name

            _log = f"trigger run on codebuild project: {project_name}, build_id: {self.build_id}, build_expire_at: {self.build_expire_at}"
            self.logger.debug(_log)
            self.phase_result["logs"].append(_log)

            return new_build
        except Exception as e:
            self.logger.error(f"Failed to trigger build: {str(e)}")
            raise

    def _submit(self, sparse_env_vars=True):
        """Submit build to CodeBuild."""
        self.phase_result = self.new_phase("submit")

        try:
            # we don't want to clobber the intact stateful files from creation
            if self.method == "create":
                self.upload_to_s3_stateful()
                self.phase_result["executed"].append("upload_to_s3")

            self.trigger_build(sparse_env_vars=sparse_env_vars)
            self.phase_result["executed"].append("trigger_codebuild")
            self.phase_result["status"] = True
            
        except Exception as e:
            self.logger.error(f"Failed to submit build: {str(e)}")
            self.phase_result["status"] = False
            self.phase_result["error"] = str(e)
            
        self.results["phases_info"].append(self.phase_result)
        return self.results

    def check(self, wait_int=10, retries=12):
        """Check build status with retries."""
        try:
            self._set_current_build()

            for retry in range(retries):
                self.logger.debug(f'check: codebuild_project_name "{self.project_name}" codebuild_id "{self.build_id}" retry {retry}/{retries} {wait_int} seconds')
                if self._check_build_status():
                    return True
                sleep(wait_int)

            return None
        except Exception as e:
            self.logger.error(f"Error checking build status: {str(e)}")
            return None

    def retrieve(self, **kwargs):
        """Check build status and retrieve results."""
        self.phase_result = self.new_phase("retrieve")

        try:
            wait_int = kwargs.get("interval", 10)
            retries = kwargs.get("retries", 12)

            if not self.check(wait_int=wait_int, retries=retries):
                self.phase_result["status"] = False
                self.phase_result["error"] = "Build check timed out"
                self.results["phases_info"].append(self.phase_result)
                return self.results

            return self._retrieve()
        except Exception as e:
            self.logger.error(f"Error retrieving build: {str(e)}")
            self.phase_result["status"] = False
            self.phase_result["error"] = str(e)
            self.results["phases_info"].append(self.phase_result)
            return self.results

    def _concat_log(self):
        """Concatenate logs from different sources."""
        try:
            _output = self.download_log_from_s3()
        except Exception as e:
            self.logger.debug(f"Failed to download log from S3: {str(e)}")
            _output = None

        if not _output:
            return "\n".join(self.output) if isinstance(self.output, list) else self.output

        return f"{_output}\n{self.output if isinstance(self.output, str) else '\n'.join(self.output)}"

    def _retrieve(self):
        """Retrieve build results."""
        try:
            self._eval_build()
            self.phase_result["executed"].append("eval_build")

            if self.s3_stateful_to_share_dir():
                self.phase_result["executed"].append("s3_share_dir")

            if hasattr(self, 'clean_output'):
                self.clean_output()

            if self.output:
                self.results["output"] = self._concat_log()

            self.phase_result["status"] = True
            
        except Exception as e:
            self.logger.error(f"Failed to retrieve build results: {str(e)}")
            self.phase_result["status"] = False
            self.phase_result["error"] = str(e)
            
        self.results["phases_info"].append(self.phase_result)
        return self.results

    def run(self, sparse_env_vars=True):
        """Run complete build process - submit and retrieve."""
        try:
            self._submit(sparse_env_vars=sparse_env_vars)
            return self._retrieve()
        except Exception as e:
            self.logger.error(f"Failed to run build: {str(e)}")
            self.results["status"] = False
            self.results["failed_message"] = f"Failed to run build: {str(e)}"
            return self.results