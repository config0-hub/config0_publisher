#!/usr/bin/env python
#
from config0_publisher.cloud.aws.codebuild import CodebuildResourceHelper
from config0_publisher.resource.aws import AWSBaseBuildParams
from config0_publisher.resource.aws import TFCmdOnAWS


class CodebuildParams(AWSBaseBuildParams):

    def __init__(self,**kwargs):

        AWSBaseBuildParams.__init__(self,**kwargs)

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

        contents = '''
version: 0.2
env:
  variables:
    TMPDIR: /tmp
    TF_PATH: /usr/local/bin/terraform
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

        CodebuildParams.__init__(self,
                                 **kwargs)

        self.tfcmds = TFCmdOnAWS(runtime_env="codebuild")

    def _get_codebuildspec_prebuild(self):

        cmds = self.tfcmds.s3_to_local()
        cmds.extend(self.tfcmds.get_tf_install())
        cmds.extend(self.tfcmds.get_decrypt_buildenv_vars())
        cmds.extend(self.tfcmds.get_src_buildenv_vars())

        if self.ssm_name:
            cmds.append('echo $SSM_VALUE | base64 -d > exports.env && chmod 755 exports.env')
            cmds.append('. ./exports.env')

            contents = '''
  pre_build:
    on-failure: ABORT
    commands:
'''
        for cmd in cmds:
            contents + "\n" + f'       - {cmd}'

        return contents

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
        else:
            raise Exception("method needs to be create/destroy")

        for cmd in cmds:
            contents + "\n" + f'       - {cmd}'

        return contents

    def _get_codebuildspec_postbuild(self):

        cmds = self.tfcmds.local_to_s3()

        contents = '''
  post_build:
    commands:
'''
        for cmd in cmds:
            contents + "\n" + f'       - {cmd}'

            return contents

    def get_buildspec(self):

        init_contents = self.get_init_contents()
        prebuild = self._get_codebuildspec_prebuild()
        build = self._get_codebuildspec_build()
        postbuild = self._get_codebuildspec_postbuild()

        if self.method == "create":
            contents = init_contents + prebuild + build + postbuild
        else:
            contents = init_contents + prebuild + build  # if destroy, we skip postbuild

        return contents