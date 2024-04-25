#!/usr/bin/env python

from config0_publisher.cloud.aws.lambdabuild import LambdaResourceHelper
from config0_publisher.resource.aws import TFAwsBaseBuildParams
from config0_publisher.resource.aws import TFCmdOnAWS
from config0_publisher.utilities import print_json


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
            "TF_PATH":f"/tmp/config0/bin/{self.tf_binary}",
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

        # testtest789
        results = self.lambda_helper.results

        print(results)
        raise Exception('test test789')
        #return self.lambda_helper.results

class Lambdabuild(LambdaParams):

    def __init__(self,**kwargs):

        self.classname = "Lambdabuild"

        LambdaParams.__init__(self,
                              **kwargs)

        self.tfcmds = TFCmdOnAWS(runtime_env="lambda",
                                 run_share_dir=self.run_share_dir,
                                 app_dir=self.app_dir,
                                 envfile="build_env_vars.env",
                                 tf_binary=self.tf_binary,
                                 tf_version=self.tf_version,
                                 tf_bucket_path=self.tf_bucket_path,
                                 arch="linux_amd64"
                                 )

    def _get_prebuild_cmds(self):

        cmds = self.tfcmds.s3_to_local()
        cmds.extend(self.tfcmds.get_tf_install())
        cmds.extend(self.tfcmds.get_decrypt_buildenv_vars(openssl=False))
        cmds.append(self.tfcmds.get_src_buildenv_vars_cmd())

        return cmds

    def _get_build_cmds(self):

        if self.method == "create":
            cmds = self.tfcmds.get_tf_apply()
        elif self.method == "destroy":
            cmds = self.tfcmds.get_tf_destroy()
        elif self.method == "validate":
            cmds = self.tfcmds.get_tf_validate()
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