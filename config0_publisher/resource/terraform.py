#!/usr/bin/env python

import os

from config0_publisher.resource.tfinstaller import get_tf_install
from config0_publisher.resource.common import TFAppHelper

class TFCmdOnAWS(TFAppHelper):

    def __init__(self,**kwargs):

        self.classname = "TFCmdOnAWS"

        self.app_name = "terraform"
        self.app_dir = kwargs["app_dir"]  # e.g. var/tmp/terraform

        self.envfile = kwargs["envfile"]  # e.g. build_env_vars.env
        self.tf_bucket_path = kwargs["tf_bucket_path"]
        self.run_share_dir = kwargs["run_share_dir"]
        self.ssm_tmp_dir = "/tmp"
        self.src_env_files_cmd = None

        TFAppHelper.__init__(self,
                             binary=kwargs["binary"],
                             version=kwargs["version"],
                             arch=kwargs["arch"],
                             runtime_env=kwargs["runtime_env"])

        self.base_output_file = f'{self.stateful_dir}/output/{self.app_name}'
        self.base_generate_file = f'{self.stateful_dir}/generated/{self.app_name}'

    def get_tf_install(self):

        '''
        https://github.com/opentofu/opentofu/releases/download/v1.6.2/tofu_1.6.2_linux_amd64.zip
        '''
        
        return get_tf_install(
                runtime_env=self.runtime_env,
                binary=self.binary,
                version=self.version,
                dl_subdir=self.dl_subdir,
                tf_bucket_path=self.tf_bucket_path,
                arch=self.arch,
                bin_dir=self.bin_dir)

    # ref 4354523
    def load_env_files(self,ssm_name=None):

        '''
        # for lambda function, we use the ssm_get python cli
        #'ssm_get -name $SSM_NAME -file {self.stateful_dir}/{self.envfile}'
        #'[ -n "$SSM_NAME" ] && echo "SSM_NAME: $SSM_NAME" || echo "SSM_NAME not set"'
        '''

        # this is envfile path in the app dir
        # e.g. var/tmp/terraform/build_env_vars.env

        envfile = os.path.join(self.app_dir,
                               self.envfile)

        # load_env_files
        if self.runtime_env == "codebuild":
            cmds = [
                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
                f'/tmp/decode_file -d {self.stateful_dir}/{self.envfile} -e {self.stateful_dir}/run/{envfile}.enc'
            ]
        else:  # lambda # testtest456
            cmds = [
                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
                f'if [ -f {self.stateful_dir}/run/{envfile}.enc ]; then cat {self.stateful_dir}/run/{envfile}.enc | base64 -d > {self.stateful_dir}/{self.envfile}; fi'
            ]

        # add ssm if needed
        if ssm_name:
            cmds.extend(self.get_ssm_concat())

        # add sourcing of env files
        self._set_src_envfiles_cmd(ssm_name=ssm_name)

        cmds.append(self.src_env_files_cmd)

        return cmds

    def get_ssm_concat(self):

        if self.runtime_env == "codebuild":
            return self._get_codebuild_ssm_concat()

        return self._get_lambda_ssm_concat()

    def _get_lambda_ssm_concat(self):

        cmds = [
            'echo "############"; echo "# SSM_NAME: $SSM_NAME"; echo "############"',
            f'ssm_get -name $SSM_NAME -file {self.ssm_tmp_dir}/.ssm_value || echo "WARNING: could not fetch SSM_NAME: $SSM_NAME"',
            f'cat {self.ssm_tmp_dir}/.ssm_value'   # testtest456
        ]

        return cmds

    def _get_codebuild_ssm_concat(self):

        if os.environ.get("DEBUG_STATEFUL"):
            cmds = [ f'echo $SSM_VALUE | base64 -d >> {self.ssm_tmp_dir}/.ssm_value && cat {self.ssm_tmp_dir}/.ssm_value' ]
        else:
            cmds = [ f'echo $SSM_VALUE | base64 -d >> {self.ssm_tmp_dir}/.ssm_value' ]

        return cmds

    def _set_src_envfiles_cmd(self,ssm_name=None):

        base_cmd = f'if [ -f /{self.stateful_dir}/{self.envfile} ]; then cd /{self.stateful_dir}/; . ./{self.envfile} ; fi'

        if not ssm_name:
            self.src_env_files_cmd = base_cmd
        else:
            ssm_cmd = f'if [ -f /{self.ssm_tmp_dir}/.ssm_value ]; then cd /{self.ssm_tmp_dir}/; . ./.ssm_value; fi'
            self.src_env_files_cmd = f'{base_cmd}; {ssm_cmd}'

        return self.src_env_files_cmd

    def s3_to_local(self):

        cmds = self.reset_dirs()

        cmds.extend([
            'echo "remote bucket s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID"',
            f'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID {self.stateful_dir}/$STATEFUL_ID.zip --quiet',
            f'rm -rf {self.stateful_dir}/run > /dev/null 2>&1 || echo "stateful already removed"',
            f'unzip -o {self.stateful_dir}/$STATEFUL_ID.zip -d {self.stateful_dir}/run',
            f'rm -rf {self.stateful_dir}/$STATEFUL_ID.zip'
        ])

        return cmds

    def get_tf_init(self):

        if self.runtime_env == "codebuild":
            return [
                f'({self.base_cmd} init) || (rm -rf .terraform && {self.base_cmd} init)',
                f'{self.base_cmd} validate'
            ]

        return [
            f'({self.src_env_files_cmd}) && ({self.base_cmd} init) || (rm -rf .terraform && {self.base_cmd} init)',
            f'({self.src_env_files_cmd}) && ({self.base_cmd} validate)'
        ]

    def get_tf_plan(self):

        if self.runtime_env == "codebuild":
            return [
                f'{self.base_cmd} plan -out={self.base_output_file}/{self.start_time}.tfplan',
                f'{self.base_cmd} show -no-color -json {self.base_output_file}/{self.start_time}.tfplan > {self.base_output_file}/{self.start_time}.tfplan.json'
            ]

        return [
            f'({self.src_env_files_cmd}) && {self.base_cmd} plan -out={self.base_output_file}/{self.start_time}.tfplan',
            f'({self.src_env_files_cmd}) && {self.base_cmd} show -no-color -json {self.base_output_file}/{self.start_time}.tfplan > {self.base_output_file}/{self.start_time}.tfplan.json'
        ]

    def get_ci_check(self):

        cmds = self.get_tf_init()
        cmds.append(self.get_tf_chk_fmt(exit_on_error=True))
        cmds.extend(self.get_tf_plan())

        return cmds

    def get_tf_apply(self):

        cmds = self.get_tf_init()
        cmds.extend(self.get_tf_plan())

        if self.runtime_env == "codebuild":
            cmds.append(f'({self.base_cmd} apply {self.base_output_file}/{self.start_time}.tfplan) || ({self.base_cmd} destroy -auto-approve && exit 9)')
        else:
            cmds.append(f'({self.src_env_files_cmd}) && ({self.base_cmd} apply {self.base_output_file}/{self.start_time}.tfplan) || ({self.base_cmd} destroy -auto-approve && exit 9)')

        return cmds

    def get_tf_destroy(self):

        cmds = self.get_tf_init()

        if self.runtime_env == "codebuild":
            cmds.append(f'{self.base_cmd} destroy -auto-approve')
        else:
            cmds.append(f'({self.src_env_files_cmd}) && {self.base_cmd} destroy -auto-approve')

        return cmds

    def get_tf_chk_fmt(self,exit_on_error=True):

        if exit_on_error:
            cmd = f'{self.base_cmd} fmt -check -diff -recursive > {self.base_output_file}/tf-fmt.out'
        else:
            cmd = f'{self.base_cmd} fmt -write=false -diff -recursive > {self.base_output_file}/tf-fmt.out'

        if self.runtime_env == "codebuild":
            return cmd

        return f'{self.src_env_files_cmd}) && {cmd}'

    def get_tf_chk_drift(self):

        cmds = self.get_tf_init()
        if self.runtime_env == "codebuild":
            cmds.extend([
                f'{self.base_cmd} refresh',
                f'{self.base_cmd} plan -detailed-exitcode'
            ])
        else:
            cmds.extend([
                f'({self.src_env_files_cmd}) && {self.base_cmd} refresh',
                f'({self.src_env_files_cmd}) && {self.base_cmd} plan -detailed-exitcode'
            ])

        return cmds

##################################################################################
# scratch
##################################################################################
# def local_to_s3(self):

#    # this does not work in lambda
#    # so we won't use it for now
#    cmds = [
#      '(cd {self.stateful_dir}/run/$APP_DIR && aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate terraform-tfstate) || echo "s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate does not exists"',
#      'cd {self.stateful_dir}/run && zip -r {self.stateful_dir}.zip . ',
#      'cd {self.stateful_dir}/run && aws s3 cp {self.stateful_dir}.zip s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID',
#      'cd {self.stateful_dir}/run && rm -rf {self.stateful_dir}.zip '
#    ]

#    return cmds


# example of using encryption for both codebuild/lambda but
# but keeping as reference though practically harder to use
# for updates
#def load_env_files(self,decrypt=None,lambda_env=True):
#
#    '''
#    # for lambda function, we use the ssm_get python cli
#    #'ssm_get -name $SSM_NAME -file {self.stateful_dir}/{self.envfile}'
#    #'[ -n "$SSM_NAME" ] && echo "SSM_NAME: $SSM_NAME" || echo "SSM_NAME not set"'
#    '''
#
#    # this is envfile path in the app dir
#    # e.g. var/tmp/terraform/build_env_vars.env
#
#    envfile = os.path.join(self.app_dir,
#                           self.envfile)
#
#    if not decrypt:
#        if not lambda_env:
#            cmds = [
#                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
#                f'if [ -f {self.stateful_dir}/run/{envfile}.enc ]; then cat {self.stateful_dir}/run/{envfile}.enc | base64 -d > {self.stateful_dir}/{self.envfile}; fi'
#            ]
#
#        if lambda_env:
#            cmds = [
#                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
#                f'/tmp/decode_file -d {self.stateful_dir}/{self.envfile} -e {self.stateful_dir}/run/{envfile}.enc',
#                'if [ -n "$SSM_NAME" ]; then echo $SSM_NAME; fi',
#                'if [ -z "$SSM_NAME" ]; then echo "SSM_NAME not set"; fi',
#                f'ssm_get -name $SSM_NAME -file {self.stateful_dir}/{self.envfile} || echo "WARNING: could not fetch SSM_NAME: $SSM_NAME"'
#            ]
#    else:
#        if not lambda_env:
#            cmds = [
#                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
#                f'if [ -f {self.stateful_dir}/run/{envfile}.enc ]; then cat {self.stateful_dir}/run/{envfile}.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:$STATEFUL_ID -base64 | base64 -d > {self.stateful_dir}/{self.envfile}; fi'
#             ]
#
#        if lambda_env:
#            cmds = [
#                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
#                f'/tmp/decrypt -s $STATEFUL_ID -d {self.stateful_dir}/{self.envfile} -e {self.stateful_dir}/run/{envfile}.enc',
#                'if [ -n "$SSM_NAME" ]; then echo $SSM_NAME; fi',
#                'if [ -z "$SSM_NAME" ]; then echo "SSM_NAME not set"; fi',
#                f'ssm_get -name $SSM_NAME -file {self.stateful_dir}/{self.envfile} || echo "WARNING: could not fetch SSM_NAME: $SSM_NAME"'
#            ]
#
#    return cmds
