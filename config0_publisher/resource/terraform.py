#!/usr/bin/env python

import os

from config0_publisher.resource.tfinstaller import get_tf_install

class TFCmdOnAWS(object):

    def __init__(self,**kwargs):

        self.classname = "TFCmdOnAWS"
        self.runtime_env = kwargs["runtime_env"]
        self.run_share_dir = kwargs["run_share_dir"]
        self.app_dir = kwargs["app_dir"]  # e.g. var/tmp/terraform
        self.envfile = kwargs["envfile"]  # e.g. build_env_vars.env
        self.tf_binary = kwargs["tf_binary"]  # tofu
        self.tf_version = kwargs["tf_version"]  # 1.6.2
        self.tf_bucket_path = kwargs["tf_bucket_path"]
        self.arch = kwargs["arch"]

        self.dl_subdir = "config0/downloads"

        if self.runtime_env == "lambda":
            self.bin_dir = f"/tmp/config0/bin"
        else:
            self.bin_dir = f"/usr/local/bin"
        
        self.stateful_dir = '$TMPDIR/config0/$STATEFUL_ID'

    def reset_dirs(self):

        cmds = [
            f'rm -rf $TMPDIR/config0 > /dev/null 2>&1 || echo "config0 already removed"',
            f'mkdir -p {self.stateful_dir}/run',
            f'mkdir -p {self.stateful_dir}/output',
            f'mkdir -p {self.stateful_dir}/generated',
            f'mkdir -p $TMPDIR/{self.dl_subdir}',
            f'echo "##############"; df -h; echo "##############"'
        ]

        return cmds

    def get_tf_install(self):

        '''
        https://github.com/opentofu/opentofu/releases/download/v1.6.2/tofu_1.6.2_linux_amd64.zip
        '''
        
        return get_tf_install(
                runtime_env=self.runtime_env,
                tf_binary=self.tf_binary,
                tf_version=self.tf_version,
                dl_subdir=self.dl_subdir,
                tf_bucket_path=self.tf_bucket_path,
                arch=self.arch,
                tf_path_dir=self.bin_dir)

    # ref 4354523
    def get_decrypt_buildenv_vars(self,lambda_env=True):

        '''
        # for lambda function, we use the ssm_get python cli
        #'ssm_get -name $SSM_NAME -file {self.stateful_dir}/{self.envfile}'
        #'[ -n "$SSM_NAME" ] && echo "SSM_NAME: $SSM_NAME" || echo "SSM_NAME not set"'
        '''

        # this is envfile path in the app dir
        # e.g. var/tmp/terraform/build_env_vars.env

        envfile = os.path.join(self.app_dir,
                               self.envfile)

        if not lambda_env:
            cmds = [
                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
                f'if [ -f {self.stateful_dir}/run/{envfile}.enc ]; then cat {self.stateful_dir}/run/{envfile}.enc | base64 -d > {self.stateful_dir}/{self.envfile}; fi'
            ]

        if lambda_env:
            cmds = [
                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
                f'/tmp/decode_file -d {self.stateful_dir}/{self.envfile} -e {self.stateful_dir}/run/{envfile}.enc',
                'if [ -n "$SSM_NAME" ]; then echo $SSM_NAME; fi',
                'if [ -z "$SSM_NAME" ]; then echo "SSM_NAME not set"; fi',
                f'ssm_get -name $SSM_NAME -file {self.stateful_dir}/{self.envfile} || echo "WARNING: could not fetch SSM_NAME: $SSM_NAME"'
            ]

        return cmds

    def get_codebuild_ssm_concat(self):

        if not os.environ.get("DEBUG_STATEFUL"):
            return f'echo $SSM_VALUE | base64 -d >> {self.stateful_dir}/{self.envfile}'

        return f'echo $SSM_VALUE | base64 -d >> {self.stateful_dir}/{self.envfile} && cat {self.stateful_dir}/{self.envfile}'

    def get_src_buildenv_vars_cmd(self):
        return f'if [ -f /{self.stateful_dir}/{self.envfile} ]; then cd /{self.stateful_dir}/; . ./{self.envfile} ; fi'

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

    def get_tf_apply(self):

        base_cmd = self.get_src_buildenv_vars_cmd()

        cmds = [
            f'({base_cmd}) && (cd {self.stateful_dir}/run/$APP_DIR && {self.bin_dir}/{self.tf_binary} init) || (rm -rf .terraform && {self.bin_dir}/{self.tf_binary} init)',
            f'({base_cmd}) && cd {self.stateful_dir}/run/$APP_DIR && {self.bin_dir}/{self.tf_binary} plan -out=tfplan',
            f'({base_cmd}) && (cd {self.stateful_dir}/run/$APP_DIR && {self.bin_dir}/{self.tf_binary} apply tfplan) || ({self.bin_dir}/{self.tf_binary} destroy -auto-approve && exit 9)'
        ]

        return cmds

    def get_tf_destroy(self):

        base_cmd = self.get_src_buildenv_vars_cmd()

        cmds = [
          f'({base_cmd}) && (cd {self.stateful_dir}/run/$APP_DIR && {self.bin_dir}/{self.tf_binary} init) || (rm -rf .terraform && {self.bin_dir}/{self.tf_binary} init)',
          f'({base_cmd}) && cd {self.stateful_dir}/run/$APP_DIR && {self.bin_dir}/{self.tf_binary} destroy -auto-approve'
        ]

        return cmds

    def get_tf_chk_draft(self):

        base_cmd = self.get_src_buildenv_vars_cmd()

        cmds = [
            f'({base_cmd}) && cd {self.stateful_dir}/run/$APP_DIR && {self.bin_dir}/{self.tf_binary} init',
            f'({base_cmd}) && cd {self.stateful_dir}/run/$APP_DIR && {self.bin_dir}/{self.tf_binary} refresh',
            f'({base_cmd}) && cd {self.stateful_dir}/run/$APP_DIR && {self.bin_dir}/{self.tf_binary} plan -detailed-exitcode'
        ]

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
#def get_decrypt_buildenv_vars(self,decrypt=None,lambda_env=True):
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
