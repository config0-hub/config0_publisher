#!/usr/bin/env python

import os
from time import time
from config0_publisher.utilities import id_generator2
from config0_publisher.cloud.aws.codebuild import CodebuildResourceHelper
from config0_publisher.resource.aws import TFAwsBaseBuildParams
from config0_publisher.resource.terraform import TFCmdOnAWS

class CodebuildParams(TFAwsBaseBuildParams):

    def __init__(self,**kwargs):

        TFAwsBaseBuildParams.__init__(self,**kwargs)

        self.classname = "CodebuildParams"

        self.codebuild_basename = kwargs.get("codebuild_basename","config0-iac")

        self.codebuild_role = kwargs.get("codebuild_role",
                                         "config0-assume-poweruser")

        self.execution_id_path = kwargs.get("execution_id_path",id_generator2())

    def _set_inputargs(self):

        self.buildparams = {
            "buildspec": self.get_buildspec(),
            "remote_stateful_bucket": self.remote_stateful_bucket,
            "codebuild_basename": self.codebuild_basename,
            "aws_region": self.aws_region,
            "build_timeout": self.build_timeout,
            "method": self.method
        }

        if self.build_env_vars:
            self.buildparams["build_env_vars"] = self.build_env_vars

        return self.buildparams

    def get_init_contents(self):

        contents = f'''
version: 0.2
env:
  variables:
    TMPDIR: /tmp
    TF_PATH: /usr/local/bin/{self.binary}
'''
        if self.ssm_name:
            ssm_params_content = '''
  parameter-store:
    SSM_VALUE: $SSM_NAME
'''
            contents = contents + ssm_params_content

        final_contents = '''
phases:
'''
        contents = contents + final_contents

        return contents

    def _init_codebuild_helper(self):

        self._set_inputargs()
        self.codebuild_helper = CodebuildResourceHelper(execution_id_path=self.execution_id_path,
                                                        **self.buildparams)

    def pre_trigger(self,**inputargs):
        self._init_codebuild_helper()
        return self.codebuild_helper.pre_trigger(**inputargs)

    def submit(self,**inputargs):

        self._init_codebuild_helper()
        self.codebuild_helper.submit(**inputargs)

        return self.codebuild_helper.results

    def retrieve(self,**inputargs):
        self.codebuild_helper.retrieve(**inputargs)
        return self.codebuild_helper.results

    def run(self,**inputargs):

        self._init_codebuild_helper()
        self.codebuild_helper.run(**inputargs)

        return self.codebuild_helper.results

class Codebuild(CodebuildParams):

    def __init__(self,**kwargs):

        self.classname = "Codebuild"

        CodebuildParams.__init__(self,**kwargs)

        self.tfcmds = TFCmdOnAWS(runtime_env="codebuild",
                                 run_share_dir=self.run_share_dir,
                                 app_dir=self.app_dir,
                                 envfile="build_env_vars.env",
                                 binary=self.binary,
                                 version=self.version,
                                 tf_bucket_path=self.tf_bucket_path,
                                 arch="linux_amd64"
                                 )

        # ref 435254
        # we will do tfsec, infracost, and opa in lambda

    @staticmethod
    def _add_cmds(contents, cmds):

        for cmd in cmds:
            contents = contents + f'       - {cmd}' + "\n"

        return contents

    def _get_codebuildspec_prebuild(self):

        cmds = self.tfcmds.s3_tfpkg_to_local()
        cmds.extend(self.tfcmds.get_tf_install())
        cmds.extend(self.tfcmds.load_env_files())

        cmds_values = [list(c.values())[0] for c in cmds]

        contents = '''
  pre_build:
    on-failure: ABORT
    commands:
'''
        return self._add_cmds(contents,cmds_values)

    def _get_codebuildspec_build(self):

        contents = '''
  build:
    on-failure: ABORT
    commands:
'''

        # codebuild is limited to create,apply, and destroy
        # lambda will handle validation, pre-create,check
        if self.method in ["create", "apply"]:
            cmds = self.tfcmds.get_tf_create()
            #cmds = self.tfcmds.get_tfplan_and_apply()
        elif self.method == "destroy":
            cmds = self.tfcmds.get_tf_destroy()
        else:
            raise Exception("method needs to be create/apply/destroy")

        cmds_values = [list(c.values())[0] for c in cmds]

        contents = self._add_cmds(contents,cmds_values)

        post_build_contents = '''
  post_build:
    commands:
      - date + %s > done
      - echo "Uploading done to S3 bucket..."
      - aws s3 cp done ${OUTPUT_BUCKET}/executions/${EXECUTION_ID}/done
'''
        return contents + post_build_contents

    def get_buildspec(self):

        init_contents = self.get_init_contents()
        prebuild = self._get_codebuildspec_prebuild()
        build = self._get_codebuildspec_build()

        return init_contents + prebuild + build