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

    def __init__(self,**kwargs):

        TFAwsBaseBuildParams.__init__(self,**kwargs)

        self.classname = "LambdaParams"
        self.execution_id_path = kwargs.get("execution_id_path",id_generator2())
        self.lambda_basename = kwargs.get("lambda_basename",
                                          "config0-iac")

        self.lambda_role = kwargs.get("lambda_role",
                                      "config0-assume-poweruser")

    def _set_inputargs(self):

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

        env_vars = {
            "TF_PATH":f"/tmp/config0/bin/{self.binary}",
            "METHOD":self.method
        }

        if self.ssm_name:
            env_vars["SSM_NAME"] = self.ssm_name

        return env_vars

    def _init_lambda_helper(self):

        self._set_inputargs()
        self.lambda_helper = LambdaResourceHelper(execution_id_path=self.execution_id_path,
                                                  **self.buildparams)

    def submit(self,**inputargs):

        self._init_lambda_helper()
        self.lambda_helper.submit(**inputargs)
        return self.lambda_helper.results

    def retrieve(self,**inputargs):

        # get results from phase json file
        # which should be set
        self.lambda_helper = LambdaResourceHelper(execution_id_path=self.execution_id_path,
                                                  **self.phases_info)
        self.lambda_helper.retrieve(**inputargs)
        return self.lambda_helper.results

    def upload_to_s3(self,**inputargs):

        if not hasattr(self,"submit"):
            self.phase_result = self.new_phase("submit")

        self.lambda_helper.upload_to_s3(**inputargs)
        self.phase_result["executed"].append("upload_to_s3")

        return self.lambda_helper.results

    def pre_trigger(self,**inputargs):
        self._init_lambda_helper()
        return self.lambda_helper.pre_trigger(**inputargs)

    # TODO can remove inputargs it seems
    def run(self,**inputargs):

        self._init_lambda_helper()
        self.lambda_helper.run(**inputargs)

        return self.lambda_helper.results

class Lambdabuild(LambdaParams):

    def __init__(self,**kwargs):

        self.classname = "Lambdabuild"

        LambdaParams.__init__(self,**kwargs)

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
                                      arch="linux_amd64"
                                      )

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

    def _get_prebuild_cmds(self):
        return self.tfcmds.get_tf_install()

    def _get_build_cmds(self):

        cmds = self.tfsec_cmds.get_all_cmds()
        cmds.extend(self.infracost_cmds.get_all_cmds())

        if self.method in ["create","apply"]:
            cmds = self.tfcmds.get_tf_create()
            #cmds = self.tfcmds.get_tfplan_and_apply()
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

    def get_cmds(self):

        cmds = {}

        prebuild_cmds = self._get_prebuild_cmds()
        if prebuild_cmds:
            cmds["prebuild"] = {"cmds":prebuild_cmds}

        build_cmds = self._get_build_cmds()
        if build_cmds:
            cmds["build"] = {"cmds":build_cmds}

        return cmds
