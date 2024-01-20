#!/usr/bin/env python

import logging
import os
import boto3
from time import time

from config0_publisher.class_helper import SetClassVarsHelper
from config0_publisher.shellouts import rm_rf
from config0_publisher.loggerly import Config0Logger
from config0_publisher.shellouts import execute3

class AWSCommonConn(SetClassVarsHelper):

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

        self.tarfile = None
        self.share_dir = None
        self.run_share_dir = None
        self.stateful_id = None
        self.remote_stateful_bucket = None
        self.output = None
        self.cwd = os.getcwd()

        self.results = kwargs.get("results")

        if not self.results:
            self.results = {
                "status":None,
                "status_code":None,
                "build_status":None,
                "run_t0": int(time()),
                "phases_info": [],
                "inputargs":{},
                "env_vars":{},
            }
            self._set_buildparams(**kwargs)
        else:
            self.set_class_vars_frm_results()

        self.s3 = boto3.resource('s3')
        self.session = boto3.Session(region_name=self.aws_region)

    def new_phase(self,name):

        return {"name": name,
                "status": None,
                "executed": [],
                "output": None,
                "logs": []
                }
    def set_class_vars_frm_results(self):

        for k,v in self.results["inputargs"].items():
            if v is None:
                exp = f'self.{k}=None'
            else:
                exp = f'self.{k}="{v}"'

            exec(exp)

    def get_default_env_vars(self):

        return {
            "tmp_bucket":True,
            "log_bucket":True,
            "app_dir":None,
            "stateful_id":None,
            "remote_stateful_bucket":None,
            "run_share_dir":None,
            "share_dir":None
        }

    def _set_buildparams(self,**kwargs):

        self.method = kwargs.get("method")
        self.build_env_vars = kwargs.get("build_env_vars")

        try:
            self.build_timeout = int(kwargs.get("build_timeout",1800))
        except:
            self.build_timeout = 30

        self.build_expire_at = int(time()) + int(self.build_timeout)

        if "set_env_vars" in kwargs:
            set_env_vars = kwargs.get("set_env_vars")
        else:
            set_env_vars = self.get_default_env_vars()

        SetClassVarsHelper.__init__(self,
                                    set_env_vars=set_env_vars,
                                    kwargs=kwargs,
                                    env_vars=self.build_env_vars,
                                    default_values=kwargs.get("default_values"),
                                    set_default_null=True)

        self.set_class_vars_srcs()

        #if not self.upload_bucket:
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

        if not hasattr(self,'aws_region') or not self.aws_region:
            self.aws_region = kwargs.get("aws_region","us-east-1")

        # record these variables
        self.results["inputargs"].update(self._vars_set)
        self.results["inputargs"]["method"] = self.method
        self.results["inputargs"]["aws_region"] = self.aws_region
        self.results["inputargs"]["build_timeout"] = self.build_timeout
        self.results["inputargs"]["build_expire_at"] = self.build_expire_at
        self.results["inputargs"]["upload_bucket"] = self.upload_bucket
        self.results["inputargs"]["stateful_id"] = self.stateful_id
        self.results["inputargs"]["share_dir"] = self.share_dir
        self.results["inputargs"]["run_share_dir"] = self.run_share_dir
        self.results["inputargs"]["tarfile"] = self.tarfile

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

    def s3_stateful_to_share_dir(self):
        if not self.stateful_id:
            return

        self._rm_tarfile()

        self.s3.Bucket(self.upload_bucket).download_file(self.stateful_id,
                                                         self.tarfile)

        self._reset_share_dir()

        # ref 452345235
        # cmd = f"tar xfz {self.tarfile} -C {self.run_share_dir}/{self.app_dir}"
        cmd = f"tar xfz {self.tarfile} -C {self.run_share_dir}"

        self.execute(cmd,
                     output_to_json=False,
                     exit_error=True)

    def upload_to_s3_stateful(self):

        if not self.stateful_id:
            return

        self._rm_tarfile()

        # ref 452345235
        # we keep the app_dir
        # cmd = f"cd {self.run_share_dir}/{self.app_dir} && tar cfz {self.tarfile}.tar.gz ."
        cmd = f"cd {self.run_share_dir} && tar cfz {self.tarfile}.tar.gz ."

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

    def execute(self,cmd,**kwargs):
        return execute3(cmd,**kwargs)