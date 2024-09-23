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
    def load_env_files(self):

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
                f'if [ -f {self.stateful_dir}/run/{envfile}.enc ]; then cat {self.stateful_dir}/run/{envfile}.enc | base64 -d > {self.stateful_dir}/{self.envfile}; fi'
            ]
        else:
            cmds = [
                f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"',
                f'/tmp/decode_file -d {self.stateful_dir}/{self.envfile} -e {self.stateful_dir}/run/{envfile}.enc'
            ]

        # add ssm if needed
        cmds.extend(self._get_ssm_concat())

        # add sourcing of env files
        self._set_src_envfiles_cmd()

        cmds.append(self.src_env_files_cmd)

        return cmds

    def _get_ssm_concat(self):

        if self.runtime_env == "codebuild":
            return self._get_codebuild_ssm_concat()

        return self._get_lambda_ssm_concat()

    def _get_lambda_ssm_concat(self):

        cmds = [
            'echo "############"; echo "# SSM_NAME: $SSM_NAME"; echo "############"',
            f'ssm_get -name $SSM_NAME -file $TMPDIR/.ssm_value > /dev/null 2>&1 || echo "WARNING: could not fetch SSM_NAME: $SSM_NAME"'
        ]

        # f'cat $TMPDIR/.ssm_value'

        return cmds

    def _get_codebuild_ssm_concat(self):

        if os.environ.get("DEBUG_STATEFUL"):
            cmds = [ f'echo $SSM_VALUE | base64 -d >> $TMPDIR/.ssm_value && cat $TMPDIR/.ssm_value' ]
        else:
            cmds = [ f'echo $SSM_VALUE | base64 -d >> $TMPDIR/.ssm_value' ]

        return cmds

    def _set_src_envfiles_cmd(self):

        # with lambda, the shell is needs env_var with set +a style

        if self.runtime_env == "codebuild":
            #base_cmd = f'if [ -f {self.stateful_dir}/{self.envfile} ]; then cd {self.stateful_dir}/; while IFS= read -r line; do echo "# $line"; eval "$line"; done < ./{self.envfile}; fi'
            base_cmd = f'if [ -f {self.stateful_dir}/{self.envfile} ]; then cd {self.stateful_dir}/; . ./{self.envfile} ; fi'
        else:
            base_cmd = f'if [ -f {self.stateful_dir}/{self.envfile} ]; then cd {self.stateful_dir}/; set -a; . ./{self.envfile}; set +a; fi'

        if self.runtime_env == "codebuild":
            ssm_cmd = f'if [ -f $TMPDIR/.ssm_value ]; then cd $TMPDIR/; . ./.ssm_value; fi'
        else:
            ssm_cmd = f'if [ -f $TMPDIR/.ssm_value ]; then cd $TMPDIR/; set -a; . ./.ssm_value; set +a; fi'

        self.src_env_files_cmd = f'{base_cmd}; {ssm_cmd}'

        return self.src_env_files_cmd

    def _get_lambda_env_cmd(self,cmd):
        return f'{self.src_env_files_cmd}; {cmd}'

    def s3_tfpkg_to_local(self):

        cmds = self.reset_dirs()

        # ref 4353253452354
        cmds.extend([
            'echo "remote bucket s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID/state/src.$STATEFUL_ID.zip"',
            f'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID/state/src.$STATEFUL_ID.zip {self.stateful_dir}/src.$STATEFUL_ID.zip --quiet',
            f'rm -rf {self.stateful_dir}/run > /dev/null 2>&1 || echo "stateful already removed"',
            f'unzip -o {self.stateful_dir}/src.$STATEFUL_ID.zip -d {self.stateful_dir}/run',
            f'rm -rf {self.stateful_dir}/src.$STATEFUL_ID.zip'
        ])

        return cmds

    def _get_tf_validate(self):

        suffix_cmd = f'{self.base_cmd} validate'

        #if self.runtime_env == "codebuild":
        #    cmds = [
        #        f'{suffix_cmd}'
        #    ]
        #else:
        #    cmds = [
        #        f'({self._get_lambda_env_cmd(suffix_cmd)}'
        #    ]

        cmds=[
            f'{suffix_cmd}'
        ]

        return cmds

    def _get_tf_init(self):

        suffix_cmd = f'{self.base_cmd} init'

        if self.runtime_env == "codebuild":
            return [
                f'{suffix_cmd} || (rm -rf .terraform && {suffix_cmd})'
            ]

        return [
            f'({self._get_lambda_env_cmd(suffix_cmd)}) || (rm -rf .terraform && {self._get_lambda_env_cmd(suffix_cmd)})'
        ]

    def _get_tf_plan(self):

        if self.runtime_env == "codebuild":
            cmds = [
                f'{self.base_cmd} plan -out={self.tmp_base_output_file}.tfplan',
                f'{self.base_cmd} show -no-color -json {self.tmp_base_output_file}.tfplan > {self.tmp_base_output_file}.tfplan.json'
            ]

        cmds = [
            f'{self._get_lambda_env_cmd(self.base_cmd)} plan -out={self.tmp_base_output_file}.tfplan',
            f'{self._get_lambda_env_cmd(self.base_cmd)} show -no-color -json {self.tmp_base_output_file}.tfplan > {self.tmp_base_output_file}.tfplan.json'
        ]

        cmds.extend(self.local_output_to_s3(suffix="tfplan",last_apply=None))
        cmds.extend(self.local_output_to_s3(suffix="tfplan.json",last_apply=None))

        return cmds

    def get_tf_ci(self):

        cmds = self._get_tf_init()
        cmds.extend(self._get_tf_validate())
        cmds.extend(self.get_tf_chk_fmt(exit_on_error=True))
        cmds.extend(self._get_tf_plan())
        #cmds.extend(self.local_output_to_s3(srcfile="/tmp/$STATEFUL_ID.log",last_apply=None))

        return cmds

    def get_tf_pre_create(self):

        cmds = self._get_tf_init()
        cmds.extend(self._get_tf_validate())
        cmds.extend(self._get_tf_plan())

        return cmds

    def get_tf_apply(self):

        cmds = self._get_tf_init()
        cmds.extend(self._get_tf_validate())
        cmds.extend(self.s3_file_to_local(suffix="tfplan",last_apply=None))

        if self.runtime_env == "codebuild":
            cmds.append(f'({self.base_cmd} apply {self.base_output_file}.tfplan) || ({self.base_cmd} destroy -auto-approve && exit 9)')
        else:
            cmds.append(f'({self._get_lambda_env_cmd(self.base_cmd)} apply {self.base_output_file}.tfplan) || ({self._get_lambda_env_cmd(self.base_cmd)} destroy -auto-approve && exit 9)')

        #cmds.extend(self.local_output_to_s3(srcfile="/tmp/$STATEFUL_ID.log",last_apply=None))

        return cmds

    def get_tf_destroy(self):

        cmds = self._get_tf_init()

        if self.runtime_env == "codebuild":
            cmds.append(f'{self.base_cmd} destroy -auto-approve')
        else:
            cmds.append(f'{self._get_lambda_env_cmd(self.base_cmd)} destroy -auto-approve')

        return cmds

    def get_tf_chk_fmt(self,exit_on_error=True):

        if exit_on_error:
            cmd = f'{self.base_cmd} fmt -check -diff -recursive'
        else:
            cmd = f'{self.base_cmd} fmt -write=false -diff -recursive'

        if self.runtime_env == "codebuild":
            cmds = [cmd]
        else:
            cmds = [self._get_lambda_env_cmd(cmd)]

        cmds.extend(self.local_output_to_s3(suffix="fmt",last_apply=None))

        return cmds

    def get_tf_chk_drift(self):

        cmds = self._get_tf_init()

        if self.runtime_env == "codebuild":
            cmds.extend([
                f'{self.base_cmd} refresh',
                f'{self.base_cmd} plan -detailed-exitcode'
            ])
        else:
            cmds.extend([
                f'({self._get_lambda_env_cmd(self.base_cmd)} refresh',
                f'({self._get_lambda_env_cmd(self.base_cmd)} plan -detailed-exitcode'
            ])

        #cmds.extend(self.local_output_to_s3(srcfile="/tmp/$STATEFUL_ID.log",last_apply=None))

        return cmds