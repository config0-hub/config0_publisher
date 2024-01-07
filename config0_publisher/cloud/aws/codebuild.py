#!/usr/bin/env python

import logging
import re
import os
import boto3
import gzip
import traceback

from io import BytesIO
from time import sleep
from time import time

from config0_publisher.class_helper import SetClassVarsHelper
from config0_publisher.shellouts import rm_rf
from config0_publisher.loggerly import Config0Logger
from config0_publisher.serialization import b64_decode
from config0_publisher.shellouts import execute3
from config0_publisher.utilities import id_generator

def new_phase(name):

    return  { "name":name,
              "status":None,
              "executed":[],
              "output":None,
              "logs":[]
              }

class CodebuildResourceHelper(SetClassVarsHelper):

    def __init__(self,**kwargs):

        self.classname = "Codebuild"
        self.logger = Config0Logger(self.classname)

        # Set the logging level for Boto3 to a higher level than DEBUG
        logging.getLogger().setLevel(logging.WARNING)
        logging.getLogger('boto3').setLevel(logging.WARNING)
        logging.getLogger('botocore').setLevel(logging.WARNING)
        logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.utils').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.tasks').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.futures').setLevel(logging.WARNING)

        # need these initial variables
        self.codebuild_basename = kwargs.get("codebuild_basename","config0-iac")
        self.codebuild_region = kwargs.get("codebuild_region","us-east-1")

        session = boto3.Session(region_name=self.codebuild_region)
        self.codebuild_client = session.client('codebuild')
        self.s3 = boto3.resource('s3')

        self.cwd = os.getcwd()
        self.build_id = None
        self.project_name = None

        # this is used for continuing via the state machine
        self.results = kwargs.get("results")

        # testtest
        self.logger.debug("s0"*32)
        self.logger.json(kwargs)
        self.logger.debug("s1"*32)
        self.logger.json(self.results)
        self.logger.debug("s2"*32)
        self.logger.debug("s2"*32)
        sleep(5)

        #self.phases_params = kwargs.get("phases_params")

        if self.results:
            self._set_class_vars_frm_results()
        else:
            self.build_image = kwargs.get("build_image",'aws/codebuild/standard:7.0')
            self.image_type = kwargs.get("image_type",'LINUX_CONTAINER')
            self.compute_type = kwargs.get("compute_type","BUILD_GENERAL1_SMALL")

            self.results = {
                "build_method":"codebuild",
                "status":None,
                "status_code":None,
                "build_status":None,
                "run_t0": int(time()),
                "phases_info": [],
                "inputargs":{
                    "build_image":self.build_image,
                    "image_type":self.image_type,
                    "compute_type":self.compute_type,
                },
                "env_vars":{},
            }

        self.output = None

        self.tarfile = None
        self.share_dir = None
        self.run_share_dir = None
        self.stateful_id = None
        self.logarn = None
        self.remote_stateful_bucket = None

        self._set_buildspec_params(**kwargs)

    def _set_class_vars_frm_results(self):

        for k,v in self.results["inputargs"].items():
            if v is None:
                exp = f'self.{k}=None'
            else:
                exp = f'self.{k}="{v}"'

            # testtest456
            self.logger.debug(f"## Setting {exp}")

            exec(exp)

    def _set_buildspec_params(self,**kwargs):

        default_set_env_vars = {
            "tmp_bucket":True,
            "log_bucket":True,
            "app_dir":None,
            "stateful_id":None,
            "remote_stateful_bucket":None,
            "upload_bucket":None,
            "run_share_dir":None,
            "share_dir":None
        }

        self.buildspec = kwargs.get("buildspec")
        self.method = kwargs.get("method")
        self.build_env_vars = kwargs.get("build_env_vars")

        if "set_env_vars" in kwargs:
            set_env_vars = kwargs.get("set_env_vars")
        else:
            set_env_vars = default_set_env_vars

        try:
            self.build_timeout = int(kwargs.get("build_timeout",1800))
        except:
            self.build_timeout = 30

        self.build_expire_at = int(time()) + int(self.build_timeout)

        SetClassVarsHelper.__init__(self,
                                    set_env_vars=set_env_vars,
                                    kwargs=kwargs,
                                    env_vars=self.build_env_vars,
                                    set_default_null=True)

        self.set_class_vars_srcs()

        if self.remote_stateful_bucket:
            self.upload_bucket = self.remote_stateful_bucket
        else:
            self.upload_bucket = self.tmp_bucket

        if not self.share_dir:
            self.share_dir = "/var/tmp/share"

        if not self.stateful_id:
            return 

        if not self.run_share_dir:
            self.run_share_dir = os.path.join(self.share_dir,
                                              self.stateful_id)

        self.tarfile = os.path.join("/tmp",
                                    self.stateful_id)

        # record these variables
        self.results["inputargs"].update(self._vars_set)
        self.results["inputargs"]["method"] = self.method
        self.results["inputargs"]["codebuild_basename"] = self.codebuild_basename
        self.results["inputargs"]["codebuild_region"] = self.codebuild_region
        self.results["inputargs"]["build_timeout"] = self.build_timeout
        self.results["inputargs"]["build_expire_at"] = self.build_expire_at
        self.results["inputargs"]["upload_bucket"] = self.upload_bucket
        self.results["inputargs"]["stateful_id"] = self.stateful_id
        self.results["inputargs"]["share_dir"] = self.share_dir
        self.results["inputargs"]["run_share_dir"] = self.run_share_dir
        self.results["inputargs"]["tarfile"] = self.tarfile

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

    def _env_vars_to_codebuild_format(self):

        skip_keys = [ "AWS_ACCESS_KEY_ID",
                      "AWS_SECRET_ACCESS_KEY" ]

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

    def _test_get_with_buildspec(self):

        contents = '''version: 0.2
phases:
  install:
    commands:
      - echo "Installing system dependencies..."
      - apt-get update && apt-get install -y zip
  pre_build:
    commands:
      - aws s3 cp s3://app-env.tmp.williaumwu.eee71/meelsrivavqqdkzy /tmp/meelsrivavqqdkzy.tar.gz --quiet
      - mkdir -p /var/tmp/share/meelsrivavqqdkzy
      - tar xfz /tmp/meelsrivavqqdkzy.tar.gz -C /var/tmp/share/meelsrivavqqdkzy/
      - rm -rf /tmp/meelsrivavqqdkzy.tar.gz
      - echo "Creating a virtual environment..."
      - cd /var/tmp/share/meelsrivavqqdkzy && python3 -m venv venv
  build:
    commands:
      - export PYTHON_VERSION=`python -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"`
      - cd /var/tmp/share/meelsrivavqqdkzy
      - . venv/bin/activate
      - echo "Installing project dependencies..."
      - pip install -r src/requirements.txt
      - cp -rp src/* venv/lib/python$PYTHON_VERSION/site-packages/
  post_build:
    commands:
      - cd /var/tmp/share/meelsrivavqqdkzy
      - cd venv/lib/python$PYTHON_VERSION/site-packages/
      - zip -r /tmp/trigger-codebuild.zip .
      - aws s3 cp /tmp/trigger-codebuild.zip s3://codebuild-shared-ed-eval-d645633/trigger-codebuild.zip

'''
        return contents

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

    def _reset_share_dir(self):

        if not os.path.exists(self.run_share_dir):
            return

        os.chdir(self.cwd)
        rm_rf(self.run_share_dir)

        cmd = f"mkdir -p {self.run_share_dir}/{self.app_dir}"
        os.system(cmd)

    def _rm_tarfile(self):

        if not self.tarfile:
            return

        if not os.path.exists(self.tarfile):
            return

        os.chdir(self.cwd)
        rm_rf(self.tarfile)

    def _s3_stateful_to_share_dir(self):

        if not self.stateful_id:
            return

        self._rm_tarfile()

        self.s3.Bucket(self.upload_bucket).download_file(self.stateful_id,
                                                         self.tarfile)

        self._reset_share_dir()

        cmd = f"tar xfz {self.tarfile} -C {self.run_share_dir}/{self.app_dir}"

        self.execute(cmd,
                     output_to_json=False,
                     exit_error=True)

    def _upload_to_s3_stateful(self):

        if not self.stateful_id:
            return

        self._rm_tarfile()

        # os.chdir(self.run_share_dir)
        cmd = f"cd {self.run_share_dir}/{self.app_dir} && tar cfz {self.tarfile}.tar.gz ."

        self.execute(cmd,
                     output_to_json=False,
                     exit_error=True)


        try:
            self.s3.Bucket(self.upload_bucket).upload_file(f"{self.tarfile}.tar.gz",
                                                           self.stateful_id)
            status = True
        except:
            status = False

        if os.environ.get("DEBUG_STATEFUL"):
            self.logger.debug(f"tarfile file {self.tarfile}.tar.gz")
        else:
            self._rm_tarfile()

        if status is False:
            _log = f"tar file failed to upload to {self.upload_bucket}/{self.stateful_id}"
            self.logger.error(_log)
            raise Exception(_log)
        else:
            _log = f"tar file uploaded to {self.upload_bucket}/{self.stateful_id}"
            self.logger.debug_highlight(_log)
            self.phase_result["logs"].append(_log)

        return status

    def execute(self,cmd,**kwargs):

        return execute3(cmd,**kwargs)

    def clean_output(self):

        clean_lines = []

        if isinstance(self.output,list):
            for line in self.output:
                try:
                    clean_lines.append(line.decode("utf-8"))
                except:
                    clean_lines.append(line)
        else:
            try:
                clean_lines.append((self.output.decode("utf-8")))
            except:
                clean_lines.append(self.output)

        self.output = clean_lines

    def print_output(self):
        self.clean_output()
        for line in self.output:
            print(line)

    def submit(self):

        self.phase_result = new_phase("submit")

        self._upload_to_s3_stateful()
        self.phase_result["executed"].append("upload_to_s3")

        self._trigger_build()
        self.phase_result["executed"].append("trigger_codebuild")
        self.phase_result["status"] = True

        self.results["phases_info"].append(self.phase_result)

        return self.results

    def check(self,wait_int=10,retries=12):

        self._set_current_build()

        for retry in range(retries):
            if self._check_build_status():
                return True
            sleep(wait_int)
        return

    def retrieve(self):

        '''
        retrieve is the same as _retrieve except
        there is a check of the build status
        where the check itself times out
        '''

        self.phase_result = new_phase("retrieve")

        if not self.check(wait_int=10,retries=12):
            return

        return self._retrieve()

    def _retrieve(self):

        self._eval_build()
        self.phase_result["executed"].append("eval_build")

        self._s3_stateful_to_share_dir()
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

        # testtest456
        self.logger.debug("j1"*32)
        self.logger.json(self.results)
        self.logger.debug("j2"*32)

        return self.results

    # this is a single run and not in phases
    # we use _retrieve instead of retrieve method
    def run(self):

        self.submit()
        self._retrieve()

        return self.results
