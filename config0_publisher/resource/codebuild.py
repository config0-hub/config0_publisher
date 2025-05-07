#!/usr/bin/env python

import os
from time import time

from config0_publisher.utilities import id_generator2
from config0_publisher.cloud.aws.codebuild import CodebuildResourceHelper
from config0_publisher.resource.aws import TFAwsBaseBuildParams
from config0_publisher.resource.terraform import TFCmdOnAWS


class CodebuildParams(TFAwsBaseBuildParams):
    """Base parameters class for AWS CodeBuild jobs."""

    def __init__(self, **kwargs):
        """Initialize CodeBuild parameters."""
        TFAwsBaseBuildParams.__init__(self, **kwargs)

        self.classname = "CodebuildParams"
        self.codebuild_basename = kwargs.get("codebuild_basename", "config0-iac")
        self.codebuild_role = kwargs.get("codebuild_role", "config0-assume-poweruser")
        
        # Centralize the logs
        self.s3_output_key = os.environ.get("EXEC_INST_ID", 
                                           f'{id_generator2()}/{str(int(time()))}')

    def _set_inputargs(self):
        """Set build parameters for CodeBuild."""
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
        """Generate initial buildspec contents."""
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
        """Initialize the CodeBuild helper with build parameters."""
        try:
            self._set_inputargs()
            self.codebuild_helper = CodebuildResourceHelper(s3_output_key=self.s3_output_key,
                                                           **self.buildparams)
        except Exception as e:
            raise Exception(f"Failed to initialize CodeBuild helper: {str(e)}")

    def submit(self, **inputargs):
        """Submit a CodeBuild job."""
        try:
            self._init_codebuild_helper()
            self.codebuild_helper.submit(**inputargs)
            return self.codebuild_helper.results
        except Exception as e:
            raise Exception(f"Failed to submit CodeBuild job: {str(e)}")

    def retrieve(self, **inputargs):
        """Retrieve results from a CodeBuild job."""
        try:
            # Get results from phase json file which should be set
            self.codebuild_helper = CodebuildResourceHelper(s3_output_key=self.s3_output_key,
                                                           **self.phases_info)
            self.codebuild_helper.retrieve(**inputargs)
            return self.codebuild_helper.results
        except Exception as e:
            raise Exception(f"Failed to retrieve CodeBuild results: {str(e)}")

    def run(self, **inputargs):
        """Run a CodeBuild job and wait for completion."""
        try:
            self._init_codebuild_helper()
            self.codebuild_helper.run(**inputargs)
            return self.codebuild_helper.results
        except Exception as e:
            raise Exception(f"Failed to run CodeBuild job: {str(e)}")


class Codebuild(CodebuildParams):
    """Implementation of CodeBuild with Terraform commands."""

    def __init__(self, **kwargs):
        """Initialize Codebuild with Terraform command support."""
        self.classname = "Codebuild"
        
        CodebuildParams.__init__(self, **kwargs)

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
        """Add commands to buildspec contents."""
        for cmd in cmds:
            contents = contents + f'       - {cmd}' + "\n"

        return contents

    def _get_codebuildspec_prebuild(self):
        """Generate pre-build section of buildspec."""
        try:
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
        except Exception as e:
            raise Exception(f"Failed to generate pre-build buildspec: {str(e)}")

    def _get_codebuildspec_build(self):
        """Generate build section of buildspec."""
        try:
            contents = '''
  build:
    on-failure: ABORT
    commands:
'''
            # CodeBuild is limited to create, apply, and destroy
            # Lambda will handle validation, pre-create, check
            if self.method in ["create", "apply"]:
                cmds = self.tfcmds.get_tfplan_and_apply()
            elif self.method == "destroy":
                cmds = self.tfcmds.get_tf_destroy()
            else:
                raise Exception("method needs to be create/apply/destroy")

            cmds_values = [list(c.values())[0] for c in cmds]

            return self._add_cmds(contents, cmds_values)
        except Exception as e:
            raise Exception(f"Failed to generate build buildspec: {str(e)}")

    def get_buildspec(self):
        """Generate complete buildspec for CodeBuild job."""
        try:
            init_contents = self.get_init_contents()
            prebuild = self._get_codebuildspec_prebuild()
            build = self._get_codebuildspec_build()

            return init_contents + prebuild + build
        except Exception as e:
            raise Exception(f"Failed to generate complete buildspec: {str(e)}")