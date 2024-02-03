#!/usr/bin/env python

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
        self.run_share_dir = kwargs["run_share_dir"]
        self.app_dir = kwargs["app_dir"]

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

        self.tfcmds = TFCmdOnAWS(runtime_env="codebuild",
                                 run_share_dir=self.run_share_dir,
                                 app_dir=self.app_dir,
                                 envfile="build_env_vars.env")

    def _add_cmds(self,contents,cmds):

        for cmd in cmds:
            contents = contents + f'       - {cmd}' + "\n"

        return contents

    def _get_codebuildspec_prebuild(self):

        cmds = self.tfcmds.get_reset_dirs()
        cmds.extend(self.tfcmds.s3_to_local())
        cmds.extend(self.tfcmds.get_tf_install(self.tf_bucket_path,
                                               self.tf_version))
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
            cmds = self.tfcmds.get_tf_validate()
        else:
            raise Exception("method needs to be create/validate/destroy")

        return self._add_cmds(contents,cmds)

def get_buildspec(self):

    init_contents = self.get_init_contents()
    prebuild = self._get_codebuildspec_prebuild()
    build = self._get_codebuildspec_build()

    contents = init_contents + prebuild + build

    # we only need postbuild if we add files, but
    # we don't modify anything b/c we use a remote
    # backend
    # if self.method == "create":
    #    postbuild = self._get_codebuildspec_postbuild()
    #    contents = init_contents + prebuild + build + postbuild
    # else:
    #    contents = init_contents + prebuild + build  # if destroy, we skip postbuild

    return contents

#    def _get_codebuildspec_postbuild(self):
#
#        cmds = self.tfcmds.local_to_s3()
#
#        contents = '''
#  post_build:
#    commands:
#'''
#        return self._add_cmds(contents,cmds)