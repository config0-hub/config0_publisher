#!/usr/bin/env python

import os
from time import time

from config0_publisher.cloud.aws.lambdabuild import LambdaResourceHelper
from config0_publisher.resource.aws import TFAwsBaseBuildParams
from config0_publisher.resource.terraform import TFCmdOnAWS
from config0_publisher.resource.infracost import TFInfracostHelper
from config0_publisher.resource.tfsec import TFSecHelper
from config0_publisher.resource.opa import TFOpaHelper
from config0_publisher.utilities import id_generator2


class LambdaParams(TFAwsBaseBuildParams):
    """Base class for Lambda parameters handling."""

    def __init__(self, **kwargs):
        """Initialize Lambda parameters."""
        TFAwsBaseBuildParams.__init__(self, **kwargs)

        self.classname = "LambdaParams"
        self.lambda_basename = kwargs.get("lambda_basename", "config0-iac")
        self.lambda_role = kwargs.get("lambda_role", "config0-assume-poweruser")

        # Centralize the logs
        self.s3_output_key = os.environ.get("EXEC_INST_ID", 
                                            f'{id_generator2()}/{str(int(time()))}')

    def _set_inputargs(self):
        """Set and prepare input arguments for Lambda helper."""
        self.buildparams = {
            "init_env_vars": self.get_init_env_vars(),
            "cmds": self.get_cmds(),
            "remote_stateful_bucket": self.remote_stateful_bucket,
            "lambda_basename": self.lambda_basename,
            "aws_region": self.aws_region,
            "build_timeout": self.build_timeout,
            "method": self.method
        }

        if self.build_env_vars:
            self.buildparams["build_env_vars"] = self.build_env_vars

        return self.buildparams

    def get_init_env_vars(self):
        """Get initialization environment variables."""
        env_vars = {
            "TF_PATH": f"/tmp/config0/bin/{self.binary}",
            "METHOD": self.method
        }

        if self.ssm_name:
            env_vars["SSM_NAME"] = self.ssm_name

        return env_vars

    def _init_lambda_helper(self):
        """Initialize the Lambda resource helper."""
        try:
            self._set_inputargs()
            self.lambda_helper = LambdaResourceHelper(s3_output_key=self.s3_output_key,
                                                      **self.buildparams)
        except Exception as e:
            raise Exception(f"Failed to initialize lambda helper: {str(e)}")

    def submit(self, **inputargs):
        """Submit Lambda task."""
        try:
            self._init_lambda_helper()
            self.lambda_helper.submit(**inputargs)
            return self.lambda_helper.results
        except Exception as e:
            raise Exception(f"Lambda submission failed: {str(e)}")

    def retrieve(self, **inputargs):
        """Retrieve results from Lambda execution."""
        try:
            # Get results from phase json file which should be set
            self.lambda_helper = LambdaResourceHelper(s3_output_key=self.s3_output_key,
                                                      **self.phases_info)
            self.lambda_helper.retrieve(**inputargs)
            return self.lambda_helper.results
        except Exception as e:
            raise Exception(f"Failed to retrieve Lambda results: {str(e)}")

    def upload_to_s3(self, **inputargs):
        """Upload artifacts to S3."""
        try:
            if not hasattr(self, "submit"):
                self.phase_result = self.new_phase("submit")

            self.lambda_helper.upload_to_s3(**inputargs)
            self.phase_result["executed"].append("upload_to_s3")

            return self.lambda_helper.results
        except Exception as e:
            raise Exception(f"Failed to upload to S3: {str(e)}")

    def run(self, **inputargs):
        """Run Lambda execution."""
        try:
            self._init_lambda_helper()
            self.lambda_helper.run(**inputargs)
            return self.lambda_helper.results
        except Exception as e:
            raise Exception(f"Lambda execution failed: {str(e)}")


class Lambdabuild(LambdaParams):
    """Class for building Lambda functions."""

    def __init__(self, **kwargs):
        """Initialize Lambda build resources."""
        self.classname = "Lambdabuild"

        LambdaParams.__init__(self, **kwargs)

        try:
            self.tfcmds = TFCmdOnAWS(runtime_env="lambda",
                                     run_share_dir=self.run_share_dir,
                                     app_dir=self.app_dir,
                                     envfile="build_env_vars.env",
                                     binary=self.binary,
                                     version=self.version,
                                     tf_bucket_path=self.tf_bucket_path,
                                     arch="linux_amd64")

            self.tfsec_cmds = TFSecHelper(runtime_env="lambda",
                                          envfile="build_env_vars.env",
                                          binary='tfsec',
                                          version="1.28.10",
                                          tmp_bucket=self.tmp_bucket,
                                          arch="linux_amd64")

            self.infracost_cmds = TFInfracostHelper(runtime_env="lambda",
                                                    envfile="build_env_vars.env",
                                                    binary='infracost',
                                                    version="0.10.39",
                                                    tmp_bucket=self.tmp_bucket,
                                                    arch="linux_amd64")

            self.opa_cmds = TFOpaHelper(runtime_env="lambda",
                                        envfile="build_env_vars.env",
                                        binary='opa',
                                        version="0.68.0",
                                        tmp_bucket=self.tmp_bucket,
                                        arch="linux_amd64")
        except Exception as e:
            raise Exception(f"Failed to initialize build resources: {str(e)}")

    def _get_prebuild_cmds(self):
        """Get pre-build commands."""
        try:
            return self.tfcmds.get_tf_install()
        except Exception as e:
            raise Exception(f"Failed to get pre-build commands: {str(e)}")

    def _get_build_cmds(self):
        """Get build commands based on method."""
        try:
            cmds = self.tfsec_cmds.get_all_cmds()
            cmds.extend(self.infracost_cmds.get_all_cmds())

            if self.method in ["create", "apply"]:
                cmds = self.tfcmds.get_tfplan_and_apply()
            elif self.method == "pre-create":
                cmds.extend(self.tfcmds.get_tf_pre_create())
            elif self.method == "validate":
                cmds.extend(self.tfcmds.get_tf_chk_drift())
            elif self.method == "check":
                cmds.extend(self.tfcmds.get_tf_ci())
            elif self.method == "destroy":
                cmds = self.tfcmds.get_tf_destroy()
            else:
                raise Exception("method needs to be create/validate/pre-create/check/apply/destroy")

            return cmds
        except Exception as e:
            raise Exception(f"Failed to get build commands: {str(e)}")

    def get_cmds(self):
        """Get all commands for execution."""
        cmds = {}

        try:
            prebuild_cmds = self._get_prebuild_cmds()
            if prebuild_cmds:
                cmds["prebuild"] = {"cmds": prebuild_cmds}

            build_cmds = self._get_build_cmds()
            if build_cmds:
                cmds["build"] = {"cmds": build_cmds}

            return cmds
        except Exception as e:
            raise Exception(f"Failed to gather commands: {str(e)}")