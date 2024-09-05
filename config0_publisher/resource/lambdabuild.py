#!/usr/bin/env python

from config0_publisher.cloud.aws.lambdabuild import LambdaResourceHelper
from config0_publisher.resource.aws import TFAwsBaseBuildParams
from config0_publisher.resource.terraform import TFCmdOnAWS
from config0_publisher.resource.infracost import TFInfracostHelper
from config0_publisher.resource.tfsec import TFSecHelper
from config0_publisher.resource.opa import TFOpaHelper

class LambdaParams(TFAwsBaseBuildParams):

    def __init__(self,**kwargs):

        TFAwsBaseBuildParams.__init__(self,**kwargs)

        self.classname = "LambdaParams"

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
            "TMPDIR":"/tmp",
            "TF_PATH":f"/tmp/config0/bin/{self.binary}",
            "METHOD":self.method
        }

        if self.ssm_name:
            env_vars["SSM_NAME"] = self.ssm_name

        return env_vars

    def _init_lambda_helper(self):

        self._set_inputargs()
        self.lambda_helper = LambdaResourceHelper(**self.buildparams)

    def submit(self,**inputargs):

        self._init_lambda_helper()
        self.lambda_helper.submit(**inputargs)

        return self.lambda_helper.results

    def retrieve(self,**inputargs):

        # get results from phase json file
        # which should be set
        self.lambda_helper = LambdaResourceHelper(**self.phases_info)
        self.lambda_helper.retrieve(**inputargs)

        return self.lambda_helper.results

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

        cmds = self.tfcmds.s3_to_local()
        cmds.extend(self.tfcmds.get_tf_install())
        cmds.extend(self.tfcmds.get_decrypt_buildenv_vars(lambda_env=True))
        cmds.append(self.tfcmds.get_src_buildenv_vars_cmd())

        return cmds

    def _get_build_cmds(self):

        if self.method == "create":
            cmds = self.tfsec_cmds.get_all_cmds()
            cmds = self.infracost_cmds.get_all_cmds()
            cmds.extend(self.tfcmds.get_tf_apply())
            #cmds.extend(self.tfsec_cmds.get_all_cmds())
            #cmds.extend(self.infracost_cmds.get_all_cmds())
            #cmds.extend(self.opa_cmds.get_all_cmds())

        elif self.method == "destroy":
            cmds = self.tfcmds.get_tf_destroy()
        elif self.method == "validate":
            cmds = self.tfcmds.get_tf_chk_drift()
        else:
            raise Exception("method needs to be create/validate/destroy")

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