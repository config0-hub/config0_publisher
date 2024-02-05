#!/usr/bin/env python

import re
import gzip
import traceback

from io import BytesIO
from time import sleep
from time import time

#from config0_publisher.utilities import print_json
from config0_publisher.cloud.aws.common import AWSCommonConn

class CodebuildResourceHelper(AWSCommonConn):

    def __init__(self,**kwargs):

        self.buildspec = kwargs.get("buildspec")

        self.build_id = None
        self.project_name = None
        self.logarn = None

        default_values = {
            "build_image":'aws/codebuild/standard:7.0',
            "image_type":'LINUX_CONTAINER',
            "compute_type":"BUILD_GENERAL1_SMALL",
            "codebuild_basename":"config0-iac"
        }

        if "set_env_vars" in kwargs:
            kwargs["set_env_vars"] = self.get_set_env_vars()

        AWSCommonConn.__init__(self,
                               default_values=default_values,
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

    def get_set_env_vars(self):

        return {
            "tmp_bucket":True,
            "log_bucket":True,
            "build_image":True,
            "image_type":True,
            "compute_type":True,
            "codebuild_basename":True,
            "app_dir":None,
            "stateful_id":None,
            "remote_stateful_bucket":None,
            "run_share_dir":None,
            "share_dir":None
        }

    def _get_build_status(self,build_ids):

        results = {}

        builds = self.codebuild_client.batch_get_builds(ids=build_ids)['builds']

        for build in builds:

            results[build["id"]] = { "status":build["buildStatus"],
                                     "logarn":build["logs"]["s3LogsArn"] }

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

        done = [ "SUCCEEDED",
                 "STOPPED",
                 "TIMED_OUT",
                 "FAILED_WITH_ABORT",
                 "FAILED",
                 "FAULT" ]

        if build_status in done:
            return build_status

    def _set_build_status_codes(self):

        build_status = self.results["build_status"]

        if build_status == 'SUCCEEDED':
            self.results["status_code"] = "successful"
            self.results["status"] = True
            return True

        failed_message = f"codebuld failed with build status {build_status}"

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
        status = None

        while True:

            sleep(5)

            if self._check_build_status() and self._set_build_status_codes():
                status = True
                break

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

        self.wait_for_log()
        self.results["time_elapsed"] = int(time()) - self.results["run_t0"]

        if not self.output:
            self.output = 'Could not get log build_id "{}"'.format(self.build_id)

        return status

    def wait_for_log(self):

        maxtime = 30
        t0 = int(time())

        build_id_suffix = self.build_id.split(":")[1]

        results = {"status":None}

        while True:

            _time_elapsed = int(time()) - t0

            if _time_elapsed > maxtime:
                self.logger.debug("time expired to retrieved log {} seconds".format(str(_time_elapsed)))
                return False

            results = self._get_log(build_id_suffix)

            if results.get("status") == True:
                return True

            if results.get("status") is False and results.get("failed_message"):
                self.logger.warn(results["failed_message"])
                return False

            sleep(2)

    def _get_log(self,build_id_suffix):

        if self.output:
            return {"status":True}

        if self.logarn:
            _log_elements = self.logarn.split("/codebuild/logs/")
            _logname = "codebuild/logs/{}".format(_log_elements[1])
            _log_bucket = _log_elements[0].split("arn:aws:s3:::")[1]
        else:
            _logname = "codebuild/logs/{}.gz".format(build_id_suffix)
            _log_bucket = self.log_bucket

        _dstfile = '/tmp/{}.gz'.format(build_id_suffix)

        try:
            obj = self.s3.Object(_log_bucket,
                                 _logname)

            _read = obj.get()['Body'].read()
        except:
            msg = traceback.format_exc()
            failed_message = "failed to get log: s3://{}/{}\n\nstacktrace:\n\n{}".format(_log_bucket,
                                                                                         _logname,
                                                                                         msg)
            return {"status":False,
                    "failed_message":failed_message}

        self.logger.debug("retrieved log: s3://{}/{}".format(_log_bucket,
                                                             _logname))

        gzipfile = BytesIO(_read)
        gzipfile = gzip.GzipFile(fileobj=gzipfile)
        log = gzipfile.read().decode('utf-8')

        self.output = log

        return {"status":True}

    def _set_build_summary(self):

        if self.results["status_code"] == "successful":
            summary_msg = "# Successful \n# build_id {}".format(self.build_id)

        elif self.results["status_code"] == "timed_out":
            summary_msg = "# Timed out \n# build_id {}".format(self.build_id)

        elif self.build_id is False:
            self.results["status_code"] = "failed"
            summary_msg = "# Never Triggered"

        elif self.build_id:
            self.results["status_code"] = "failed"
            summary_msg = "# Failed \n# build_id {}".format(self.build_id)

        else:
            self.results["status_code"] = "failed"
            summary_msg = "# Never Triggered"

        self.results["msg"] = summary_msg

        return summary_msg

    def _env_vars_to_codebuild_format(self,sparse=True):

        skip_keys = [ "AWS_ACCESS_KEY_ID",
                      "AWS_SECRET_ACCESS_KEY" ]

        sparse_keys = [ "STATEFUL_ID",
                        "REMOTE_STATEFUL_BUCKET",
                        "TMPDIR",
                        "APP_DIR" ]

        env_vars = []
        _added = []

        if not self.build_env_vars:
            return env_vars

        pattern = r"^CODEBUILD"

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

            _env_var = { 'name': _k,
                         'value': _v,
                         'type': 'PLAINTEXT'}

            env_vars.append(_env_var)

        return env_vars

    def _get_avail_codebuild_projects(self,max_queue_size=5):

        results = {}

        # Get a list of all projects
        response = self.codebuild_client.list_projects()

        for project in response['projects']:

            if self.codebuild_basename not in project:
                continue

            response = self.codebuild_client.list_builds_for_project(projectName=project,
                                                                     sortOrder='ASCENDING')

            if not response["ids"]:
                results[project] = 0
                continue

            build_statues = self._get_build_status(response["ids"])

            current_build_ids = []

            for build_id,build_status in build_statues.items():

                if build_status == "IN_PROGRESS":
                    current_build_ids.append(build_id)
                    continue

            if not current_build_ids:
                results[project] = 0
                continue

            build_count = len(current_build_ids)

            self.logger.debug(f"Project: {project}, Build Count: {build_count}")

            if build_count < max_queue_size:
                results[project] = build_count

        if not results:
            return

        return sorted(results, key=lambda x: results[x])

    def _get_codebuild_projects(self,sleep_int=10):

        for retry in range(3):

            try:
                empty_queue_projects = self._get_avail_codebuild_projects()
            except:
                empty_queue_projects = False

            if empty_queue_projects:
                return empty_queue_projects

            sleep(sleep_int)

        return False

    def _trigger_build(self):

        projects = self._get_codebuild_projects()

        if not projects:
            raise Exception("could not find a codebuild project that has availability capacity")

        try:
            timeout = int(self.build_timeout/60)
        except:
            timeout = 60

        for project_name in projects:

            self.logger.debug_highlight(f"running job on codebuild project {project_name}")

            inputargs = {"projectName":project_name,
                         "environmentVariablesOverride":self._env_vars_to_codebuild_format(),
                         "timeoutInMinutesOverride":timeout,
                         "imageOverride": self.build_image,
                         "computeTypeOverride": self.compute_type,
                         "environmentTypeOverride":self.image_type}

            if self.buildspec:
                inputargs["buildspecOverride"] = self.buildspec

            try:
                new_build = self.codebuild_client.start_build(**inputargs)
            except:
                msg = traceback.format_exc()
                self.logger.warn(f"could not start build on codebuild {project_name}\n\n{msg}")
                continue

            break

        self.project_name = project_name
        self.build_id = new_build['build']['id']

        self.results["inputargs"]["build_id"] = self.build_id
        self.results["inputargs"]["project_name"] = project_name

        _log = f"trigger run on codebuild project: {project_name}, build_id: {self.build_id}, build_expire_at: {self.build_expire_at}"
        self.logger.debug(_log)
        self.phase_result["logs"].append(_log)

        return new_build

    def _submit(self):

        self.phase_result = self.new_phase("submit")

        # we don't want to clobber the intact
        # stateful files from creation
        if self.method == "create":
            self.upload_to_s3_stateful()
            self.phase_result["executed"].append("upload_to_s3")

        self._trigger_build()

        self.phase_result["executed"].append("trigger_codebuild")
        self.phase_result["status"] = True
        self.results["phases_info"].append(self.phase_result)

        return self.results

    def check(self,wait_int=10,retries=12):

        self._set_current_build()

        for retry in range(retries):
            self.logger.debug(f'check: codebuild_project_name "{self.project_name}" codebuild_id "{self.build_id}" retry {retry}/{retries} {wait_int} seconds')
            if self._check_build_status():
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