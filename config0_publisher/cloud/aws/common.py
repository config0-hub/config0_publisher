#!/usr/bin/env python

import traceback
import logging
import botocore.session
import os
import boto3
from time import time

from config0_publisher.class_helper import SetClassVarsHelper
from config0_publisher.shellouts import rm_rf
from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import id_generator2
from config0_publisher.shellouts import execute3

class AWSCommonConn(SetClassVarsHelper):

    def __init__(self,**kwargs):

        self.classname = "AWSCommonConn"
        self.logger = Config0Logger(self.classname)

        # Set the logging level for Boto3 to a higher level than DEBUG
        logging.getLogger().setLevel(logging.WARNING)
        logging.getLogger('boto3').setLevel(logging.WARNING)
        logging.getLogger('botocore').setLevel(logging.WARNING)
        logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.utils').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.tasks').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.futures').setLevel(logging.WARNING)

        self.share_dir = None
        self.run_share_dir = None
        self.stateful_id = None
        self.remote_stateful_bucket = None
        self.output = None
        self.cwd = os.getcwd()

        self.results = kwargs.get("results")
        self.zipfile = None
        self.s3_output_folder = id_generator2()

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

        cfg = botocore.config.Config(retries={'max_attempts': 0},
                                     read_timeout=900,
                                     connect_timeout=900,
                                     region_name=self.aws_region)

        self.lambda_client = boto3.client('lambda',
                                          config=cfg,
                                          region_name=self.aws_region)

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
            self.build_timeout = int(kwargs.get("build_timeout",500))
        except:
            self.build_timeout = 500

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

        self.zipfile = os.path.join("/tmp",
                                    f'{self.stateful_id}.zip')

        # we hard wire to us-east-1 to avoid
        # any environmental variable changes the region
        self.aws_region = "us-east-1"

        #if not hasattr(self,'aws_region') or not self.aws_region:
        #    self.aws_region = kwargs.get("aws_region","us-east-1")

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
        self.results["inputargs"]["zipfile"] = self.zipfile

    def _reset_share_dir(self):
        if not os.path.exists(self.run_share_dir):
            return

        os.chdir(self.cwd)
        rm_rf(self.run_share_dir)

        cmd = f"mkdir -p {self.run_share_dir}/{self.app_dir}"
        os.system(cmd)

    def _rm_zipfile(self):

        if not self.zipfile:
            return

        if not os.path.exists(self.zipfile):
            return

        os.chdir(self.cwd)
        rm_rf(self.zipfile)

    def _download_s3_stateful(self):

        # ref 542352
        bucket_keys = [
            f"{self.stateful_id}/state/src.{self.stateful_id}.zip",
            self.stateful_id
        ]

        failed_message = None

        for bucket_key in bucket_keys:

            self.logger.debug(f"attempting to get stateful s3 from {self.upload_bucket}/{bucket_key}")

            # ref 4353253452354
            try:
                self.s3.Bucket(self.upload_bucket).download_file(f"{self.stateful_id}/{bucket_key}",
                                                                 self.zipfile)
                status = True
                break
            except:
                failed_message = traceback.format_exc()
                self.logger.debug_highlight(f"could not get stateful s3 from {self.upload_bucket}/{bucket_key}")
                status = False

        if not status and failed_message:
            self.logger.warn(failed_message)

        return status

    def s3_stateful_to_share_dir(self):

        if not self.stateful_id:
            return

        self._rm_zipfile()

        if not self._download_s3_stateful():
            raise Exception("could not fetch s3 stateful")

        self._reset_share_dir()

        # ref 452345235
        cmd = f"unzip -o {self.zipfile} -d {self.run_share_dir}"

        self.execute(cmd,
                     output_to_json=False,
                     exit_error=True)

    def upload_to_s3_stateful(self):

        if not self.stateful_id:
            return

        self._rm_zipfile()

        # ref 452345235
        # we keep the app_dir
        cmd = f"cd {self.run_share_dir} && zip -r {self.zipfile} ."

        self.execute(cmd,
                     output_to_json=False,
                     exit_error=True)

        # ref 542352
        s3_dst = f'{self.stateful_id}/state/src.{self.stateful_id}.zip'

        if not s3_dst.endswith(".zip"):
            s3_dst = f'{s3_dst}.zip'

        try:
            self.s3.Bucket(self.upload_bucket).upload_file(f"{self.zipfile}",
                                                           s3_dst)
            status = True
        except:
            status = False

        if os.environ.get("DEBUG_STATEFUL"):
            self.logger.debug(f"zipfile file {self.zipfile}")
        else:
            self._rm_zipfile()

        if status is False:
            _log = f"zip file failed to upload to {s3_dst}"
            self.logger.error(_log)
            raise Exception(_log)
        else:
            _log = f"zip file uploaded to {s3_dst}"
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

    def execute(self,cmd,**kwargs):
        return execute3(cmd,**kwargs)