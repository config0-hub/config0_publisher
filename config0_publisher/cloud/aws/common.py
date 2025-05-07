#!/usr/bin/env python

"""
Base class for AWS connectivity and resource management.
Provides core AWS functionality including session management and resource access.
"""

import traceback
import logging
import botocore.session
import botocore.config
import os
import boto3
from time import time

from config0_publisher.class_helper import SetClassVarsHelper
from config0_publisher.shellouts import rm_rf
from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import id_generator2
from config0_publisher.shellouts import execute3


class AWSCommonConn(SetClassVarsHelper):
    """Base class for AWS connectivity and resource management."""

    def __init__(self, **kwargs):
        """
        Initialize AWS connection and resources.
        
        Args:
            kwargs: Keyword arguments including:
                results (dict): Existing results to continue from
                build_env_vars (dict): Environment variables for build
                build_timeout (int): Maximum build time in seconds
                method (str): Execution method (create/destroy)
                set_env_vars (dict): Environment variables to set
        """
        self.classname = "AWSCommonConn"
        self.logger = Config0Logger(self.classname)

        # Configure logging levels
        logging.getLogger().setLevel(logging.WARNING)
        logging.getLogger('boto3').setLevel(logging.WARNING)
        logging.getLogger('botocore').setLevel(logging.WARNING)
        logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.utils').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.tasks').setLevel(logging.WARNING)
        logging.getLogger('s3transfer.futures').setLevel(logging.WARNING)

        # Initialize attributes
        self.share_dir = None
        self.run_share_dir = None
        self.stateful_id = None
        self.remote_stateful_bucket = None
        self.output = None
        self.cwd = os.getcwd()
        self.results = kwargs.get("results")
        self.zipfile = None

        self.s3_output_key = os.environ.get("EXEC_INST_ID")
        if not self.s3_output_key:
            self.s3_output_key = kwargs.get("s3_output_key", 
                                           f'{id_generator2()}/{str(int(time()))}')

        if not self.results:
            self.results = {
                "status": None,
                "status_code": None,
                "build_status": None,
                "run_t0": int(time()),
                "phases_info": [],
                "inputargs": {},
                "env_vars": {},
            }
            self._set_buildparams(**kwargs)
        else:
            self.set_class_vars_frm_results()

        try:
            self.s3 = boto3.resource('s3')
            self.session = boto3.Session(region_name=self.aws_region)

            cfg = botocore.config.Config(retries={'max_attempts': 0},
                                        read_timeout=900,
                                        connect_timeout=900,
                                        region_name=self.aws_region)

            self.lambda_client = boto3.client('lambda',
                                             config=cfg,
                                             region_name=self.aws_region)
        except Exception as e:
            self.logger.error(f"Failed to initialize AWS resources: {str(e)}")
            raise

    @staticmethod
    def new_phase(name):
        """Create a new phase structure with the given name."""
        return {
            "name": name,
            "status": None,
            "executed": [],
            "output": None,
            "logs": []
        }

    def set_class_vars_frm_results(self):
        """Set class variables from stored results."""
        for k, v in self.results["inputargs"].items():
            if v is None:
                exec(f'self.{k}=None')
            else:
                exec(f'self.{k}="{v}"')

    @staticmethod
    def get_default_env_vars():
        """Get the default environment variables."""
        return {
            "tmp_bucket": True,
            "log_bucket": True,
            "app_dir": None,
            "stateful_id": None,
            "remote_stateful_bucket": None,
            "run_share_dir": None,
            "share_dir": None
        }

    def _set_buildparams(self, **kwargs):
        """Set build parameters from provided arguments."""
        self.method = kwargs.get("method")
        self.build_env_vars = kwargs.get("build_env_vars")

        try:
            self.build_timeout = int(kwargs.get("build_timeout", 600))
        except (ValueError, TypeError):
            self.build_timeout = 600

        self.build_expire_at = int(time()) + self.build_timeout

        if "set_env_vars" in kwargs:
            set_env_vars = kwargs.get("set_env_vars")
        else:
            set_env_vars = self.get_default_env_vars()

        SetClassVarsHelper.__init__(
            self,
            set_env_vars=set_env_vars,
            kwargs=kwargs,
            env_vars=self.build_env_vars,
            default_values=kwargs.get("default_values"),
            set_default_null=True
        )

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
            self.run_share_dir = os.path.join(self.share_dir, self.stateful_id)

        self.zipfile = os.path.join("/tmp", f'{self.stateful_id}.zip')

        # TODO have option to install executors in different region
        # Hard-wired to us-east-1 since executors should only be in this region for now
        self.aws_region = "us-east-1"

        # Record variables
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
        """Reset (clean and recreate) the share directory."""
        try:
            if not os.path.exists(self.run_share_dir):
                return

            os.chdir(self.cwd)
            rm_rf(self.run_share_dir)

            os.makedirs(f"{self.run_share_dir}/{self.app_dir}", exist_ok=True)
        except Exception as e:
            self.logger.error(f"Failed to reset share directory: {str(e)}")
            raise

    def _rm_zipfile(self):
        """Remove the zipfile if it exists."""
        try:
            if not self.zipfile or not os.path.exists(self.zipfile):
                return

            os.chdir(self.cwd)
            rm_rf(self.zipfile)
        except Exception as e:
            self.logger.warn(f"Failed to remove zipfile: {str(e)}")

    def download_log_from_s3(self, bucket_name=None):
        """Download log file from S3 bucket."""
        if not bucket_name:
            bucket_name = self.tmp_bucket

        local_file = f'/tmp/{id_generator2()}'

        try:
            self.s3.Bucket(bucket_name).download_file(self.s3_output_key, local_file)

            with open(local_file, 'r', encoding='utf-8') as file:
                file_content = file.read()

            rm_rf(local_file)
            return file_content
        except Exception as e:
            self.logger.error(f"Failed to download log from S3: {str(e)}")
            if os.path.exists(local_file):
                rm_rf(local_file)
            raise

    def _download_s3_stateful(self):
        """Download stateful files from S3."""
        bucket_keys = [
            self.stateful_id,
            f"{self.stateful_id}/state/src.{self.stateful_id}.zip"
        ]

        failed_message = None
        status = False

        for bucket_key in bucket_keys:
            self.logger.debug(f"Attempting to get stateful s3 from {self.upload_bucket}/{bucket_key}")

            try:
                self.s3.Bucket(self.upload_bucket).download_file(
                    f"{self.stateful_id}/{bucket_key}",
                    self.zipfile
                )
                status = True
                break
            except Exception:
                failed_message = traceback.format_exc()
                status = False

        if os.environ.get("JIFFY_ENHANCED_LOG") and not status and failed_message:
            self.logger.warn(failed_message)

        if not status:
            self.logger.debug_highlight(f"Could not get stateful s3 from {self.upload_bucket}/{bucket_key}")

        return status

    def s3_stateful_to_share_dir(self):
        """Transfer S3 stateful content to local share directory."""
        if not self.stateful_id:
            return

        self._rm_zipfile()

        if not self._download_s3_stateful():
            return

        self._reset_share_dir()

        try:
            cmd = f"unzip -o {self.zipfile} -d {self.run_share_dir}"
            self.execute(cmd, output_to_json=False, exit_error=True)
        except Exception as e:
            self.logger.error(f"Failed to extract stateful archive: {str(e)}")
            raise

    def upload_to_s3_stateful(self):
        """Upload local content to S3 as stateful archive."""
        if not self.stateful_id:
            return

        self._rm_zipfile()

        try:
            cmd = f"cd {self.run_share_dir} && zip -r {self.zipfile} ."
            self.execute(cmd, output_to_json=False, exit_error=True)

            s3_dst = f'{self.stateful_id}/state/src.{self.stateful_id}.zip'
            if not s3_dst.endswith(".zip"):
                s3_dst = f'{s3_dst}.zip'

            self.s3.Bucket(self.upload_bucket).upload_file(self.zipfile, s3_dst)
            status = True
            
            _log = f"Zip file uploaded to {s3_dst}"
            self.logger.debug_highlight(_log)
            if hasattr(self, 'phase_result'):
                self.phase_result["logs"].append(_log)
        except Exception as e:
            status = False
            _log = f"Zip file failed to upload to {s3_dst}: {str(e)}"
            self.logger.error(_log)
            raise Exception(_log)
        finally:
            if os.environ.get("DEBUG_STATEFUL"):
                self.logger.debug(f"Zipfile file {self.zipfile}")
            else:
                self._rm_zipfile()

        return status

    def clean_output(self):
        """Clean and decode output data."""
        clean_lines = []

        try:
            if isinstance(self.output, list):
                for line in self.output:
                    try:
                        clean_lines.append(line.decode("utf-8"))
                    except (UnicodeDecodeError, AttributeError):
                        clean_lines.append(line)
            else:
                try:
                    clean_lines.append(self.output.decode("utf-8"))
                except (UnicodeDecodeError, AttributeError):
                    clean_lines.append(self.output)

            self.output = clean_lines
        except Exception as e:
            self.logger.warn(f"Error cleaning output: {str(e)}")
            # Keep original output if cleaning fails
            pass

    @staticmethod
    def execute(cmd, **kwargs):
        """Execute a shell command with the provided arguments."""
        return execute3(cmd, **kwargs)