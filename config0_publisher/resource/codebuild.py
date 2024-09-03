#!/usr/bin/env python

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
    TF_PATH: /usr/local/bin/{self.tf_binary}
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
        self.codebuild_helper = CodebuildResourceHelper(**self.buildparams)

    def submit(self,**inputargs):

        self._init_codebuild_helper()
        self.codebuild_helper.submit(**inputargs)

        return self.codebuild_helper.results

    def retrieve(self,**inputargs):

        # get results from phase json file
        # which should be set
        self.codebuild_helper = CodebuildResourceHelper(**self.phases_info)
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
                                 tf_binary=self.tf_binary,
                                 tf_version=self.tf_version,
                                 tf_bucket_path=self.tf_bucket_path,
                                 arch="linux_amd64"
                                 )

    def _add_cmds(self,contents,cmds):

        for cmd in cmds:
            contents = contents + f'       - {cmd}' + "\n"

        return contents

    def _get_codebuildspec_prebuild(self):

        cmds = self.tfcmds.s3_to_local()
        cmds.extend(self.tfcmds.get_tf_install())
        cmds.extend(self.tfcmds.get_decrypt_buildenv_vars(lambda_env=None))

        if self.ssm_name:
            cmds.append(self.tfcmds.get_codebuild_ssm_concat())

        base_cmd = self.tfcmds.get_src_buildenv_vars_cmd()
        cmds.append(base_cmd)

        contents = '''
  pre_build:
    on-failure: ABORT
    commands:
'''
        return self._add_cmds(contents,cmds)

    def _get_codebuildspec_build(self):

        contents = '''
  build:
    on-failure: ABORT
    commands:
'''
        if self.method == "create":
            cmds = self.tfcmds.get_tf_apply()
        elif self.method == "destroy":
            cmds = self.tfcmds.get_tf_destroy()
        elif self.method == "validate":
            cmds = self.tfcmds.get_tf_chk_draft()
        else:
            raise Exception("method needs to be create/validate/destroy")

        return self._add_cmds(contents,cmds)

    def get_buildspec(self):

        init_contents = self.get_init_contents()
        prebuild = self._get_codebuildspec_prebuild()
        build = self._get_codebuildspec_build()

        return init_contents + prebuild + build