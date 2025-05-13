#!/usr/bin/env python

import os
from time import time

from config0_publisher.utilities import id_generator2
from config0_publisher.cloud.aws.codebuild2 import CodebuildResourceHelper
from config0_publisher.cloud.aws.stepf import StepFuncIacOrchestrator
from config0_publisher.resource.aws import TFAwsBaseBuildParams
from config0_publisher.resource.terraform import TFCmdOnAWS

class CodebuildParams(TFAwsBaseBuildParams):
    def __init__(self, **kwargs):
        TFAwsBaseBuildParams.__init__(self, **kwargs)

        self.classname = "CodebuildParams"
        self.codebuild_basename = kwargs.get("codebuild_basename", "config0-iac")
        self.codebuild_role = kwargs.get("codebuild_role", "config0-assume-poweruser")
        
        # to centralize the logs
        self.s3_output_key = os.environ.get("EXEC_INST_ID", 
                                            f'{id_generator2()}/{str(int(time()))}')

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
            contents += ssm_params_content

        contents += '''
phases:
'''
        return contents

    def get_base_event(self):
        self._set_inputargs()
        codebuild_helper = CodebuildResourceHelper(s3_output_key=self.s3_output_key,
                                                **self.buildparams)
        return codebuild_helper.get_base_event()


class Codebuild(CodebuildParams):
    def __init__(self, **kwargs):
        self.classname = "Codebuild"
        CodebuildParams.__init__(self, **kwargs)

        self.tfcmds = TFCmdOnAWS(runtime_env="codebuild",
                               run_share_dir=self.run_share_dir,
                               app_dir=self.app_dir,
                               envfile="build_env_vars.env",
                               binary=self.binary,
                               version=self.version,
                               tf_bucket_path=self.tf_bucket_path,
                               arch="linux_amd64")

        self.stepf = StepFuncIacOrchestrator(state_machine_name="config0-iac",
                                             s3_bucket=self.tmp_bucket,
                                             region=self.aws_region)

    @staticmethod
    def _add_cmds(contents, cmds):
        for cmd in cmds:
            contents += f'       - {cmd}\n'
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
        return self._add_cmds(contents, cmds_values)

    def _get_codebuildspec_build(self):
        contents = '''
  build:
    on-failure: ABORT
    commands:
'''
        # codebuild is limited to create, apply, and destroy
        # lambda will handle validation, pre-create, check
        if self.method in ["create", "apply"]:
            cmds = self.tfcmds.get_tfplan_and_apply()
        elif self.method == "destroy":
            cmds = self.tfcmds.get_tf_destroy()
        else:
            raise ValueError("method needs to be create/apply/destroy")

        cmds_values = [list(c.values())[0] for c in cmds]
        return self._add_cmds(contents, cmds_values)

    def get_buildspec(self):
        init_contents = self.get_init_contents()
        prebuild = self._get_codebuildspec_prebuild()
        build = self._get_codebuildspec_build()
        return init_contents + prebuild + build

    def get_event(self):
        event = self.get_base_event()
        event["s3_bucket"] = self.tmp_bucket
        event["s3_key"] = self.s3_output_key
        return event

    def run(self):
        event = self.get_event()
        self.stepf.invoke_with_codebuild(**event)
