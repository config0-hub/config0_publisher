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

        # if initial apply, then if apply fails, it will automatically destroy
        self.initial_apply = kwargs.get("initial_apply")

        self.tf_bucket_path = kwargs["tf_bucket_path"]
        self.run_share_dir = kwargs["run_share_dir"]
        self.ssm_tmp_dir = "/tmp"

        TFAppHelper.__init__(self,
                             binary=kwargs["binary"],
                             version=kwargs["version"],
                             arch=kwargs["arch"],
                             runtime_env=kwargs["runtime_env"])

    def get_tf_install(self):

        """
        https://github.com/opentofu/opentofu/releases/download/v1.6.2/tofu_1.6.2_linux_amd64.zip
        """
        
        return get_tf_install(
                runtime_env=self.runtime_env,
                binary=self.binary,
                version=self.version,
                tf_bucket_path=self.tf_bucket_path,
                arch=self.arch,
                bin_dir=self.bin_dir)

    # ref 4354523
    # used only for codebuild
    @staticmethod
    def _get_ssm_concat_cmds():

        base_cmd = f'echo $SSM_VALUE | base64 -d >> $TMPDIR/.ssm_value'

        if os.environ.get("DEBUG_STATEFUL"):
            cmds = [ {"_get_ssm_concat_cmds": f'({base_cmd} && cat $TMPDIR/.ssm_value) || echo "could not evaluate SSM_VALUE"'} ]
        else:
            cmds = [ {"_get_ssm_concat_cmds": f'{base_cmd} || echo "could not evaluate $SSM_VALUE"'} ]

        return cmds

    # used only for codebuild
    def _set_src_envfiles_cmd(self):

        base_cmd = f'if [ -f {self.stateful_dir}/{self.envfile} ]; then cd {self.stateful_dir}/; . ./{self.envfile} ; fi'
        ssm_cmd = f'if [ -f $TMPDIR/.ssm_value ]; then cd $TMPDIR/; . ./.ssm_value; fi'

        return { "_set_src_envfiles_cmd": f'{base_cmd}; {ssm_cmd}' }

    # used only for codebuild
    def load_env_files(self):

        # this is envfile path in the app dir
        # e.g. var/tmp/terraform/build_env_vars.env
        envfile = os.path.join(self.app_dir,
                               self.envfile)

        cmds = [
            { "load_env_file - remove existing env" : f'rm -rf {self.stateful_dir}/{envfile} > /dev/null 2>&1 || echo "env file already removed"' },
            { "load_env_file - load env " : f'if [ -f {self.stateful_dir}/run/{envfile}.enc ]; then cat {self.stateful_dir}/run/{envfile}.enc | base64 -d > {self.stateful_dir}/{self.envfile}; fi' }
        ]

        # testtest456 need to modify this for SSM_NAMES plural
        cmds.extend(self._get_ssm_concat_cmds())
        cmds.append(self._set_src_envfiles_cmd())

        return cmds

    def s3_tfpkg_to_local(self):

        cmds = self.reset_dirs()

        # ref 4353253452354
        cmds.extend([
            { "s3_tfpkg_to_local - echo bucket": 'echo "remote bucket s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID/state/src.$STATEFUL_ID.zip"' },
            { "s3_tfpkg_to_local - aws copy source": f'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID/state/src.$STATEFUL_ID.zip {self.stateful_dir}/src.$STATEFUL_ID.zip --quiet' },
            { "s3_tfpkg_to_local - clean src dir": f'rm -rf {self.stateful_dir}/run > /dev/null 2>&1 || echo "stateful already removed"' },
            { "s3_tfpkg_to_local - unzip src files": f'unzip -o {self.stateful_dir}/src.$STATEFUL_ID.zip -d {self.stateful_dir}/run' },
            { "s3_tfpkg_to_local - remove download file": f'rm -rf {self.stateful_dir}/src.$STATEFUL_ID.zip' }
        ])

        return cmds

    def _get_tf_validate(self):

        suffix_cmd = f'{self.base_cmd} validate'

        cmds = [
            { "_get_tf_validate": suffix_cmd }
        ]

        return cmds

    def _get_tf_init(self):

        suffix_cmd = f'{self.base_cmd} init'

        return [
            { "_get_tf_init" : f'{suffix_cmd} || (rm -rf .terraform && {suffix_cmd})' }
        ]

    def _get_tf_plan(self):

        cmds = [
            { "_get_tf_plan - create plan": f'{self.base_cmd} plan -out={self.tmp_base_output_file}.tfplan' },
            { "_get_tf_plan - plan to json": f'{self.base_cmd} show -no-color -json {self.tmp_base_output_file}.tfplan > {self.tmp_base_output_file}.tfplan.json' }
        ]

        cmds.extend(self.local_output_to_s3(suffix="tfplan",last_apply=None))
        cmds.extend(self.local_output_to_s3(suffix="tfplan.json",last_apply=None))

        return cmds

    def get_tf_ci(self):

        cmds = self._get_tf_init()
        cmds.extend(self._get_tf_validate())
        cmds.extend(self.get_tf_chk_fmt(exit_on_error=True))
        cmds.extend(self._get_tf_plan())

        return cmds

    def get_tf_pre_create(self):

        cmds = self._get_tf_init()
        cmds.extend(self._get_tf_validate())
        cmds.extend(self._get_tf_plan())

        return cmds

    def get_tf_create(self,destroy_on_failure=None):
        cmds = self._get_tf_init()
        cmds.extend(self._get_tf_validate())
        cmds.extend(self._get_tf_plan())

        base_tf_apply = f'{self.base_cmd} apply {self.base_output_file}.tfplan'

        cmds.extend(self.s3_file_to_local(suffix="tfplan",
                                          last_apply=None))

        if destroy_on_failure:
            cmds.append( { "get_tf_create" : f'({base_tf_apply}) || ({self.base_cmd} destroy -auto-approve && exit 9)' } )
        else:
            cmds.append( { "get_tf_create" : base_tf_apply } )

        return cmds

    def get_tfplan_and_apply(self,destroy_on_failure=None):

        if self.initial_apply:
            destroy_on_failure = True

        cmds = self._get_tf_init()
        cmds.extend(self._get_tf_validate())
        cmds.extend(self.s3_file_to_local(suffix="tfplan",
                                          last_apply=None))

        base_tf_apply = f'{self.base_cmd} apply {self.base_output_file}.tfplan'

        if destroy_on_failure:
            cmds.append( { "get_tfplan_and_apply" : f'({base_tf_apply}) || ({self.base_cmd} destroy -auto-approve && exit 9)' } )
        else:
            cmds.append( { "get_tfplan_and_apply" : base_tf_apply } )

        return cmds

    def get_tf_destroy(self):

        cmds = self._get_tf_init()
        cmds.append( { "get_tf_destroy": f'{self.base_cmd} destroy -auto-approve' } )

        return cmds

    def get_tf_chk_fmt(self,exit_on_error=True):

        if exit_on_error:
            cmd = { "get_tf_chk_fmt": f'{self.base_cmd} fmt -check -diff -recursive' }
        else:
            cmd = { "get_tf_chk_fmt": f'{self.base_cmd} fmt -write=false -diff -recursive' }

        cmds= [cmd]

        cmds.extend(self.local_output_to_s3(suffix="fmt",last_apply=None))

        return cmds

    def get_tf_chk_drift(self):

        cmds = self._get_tf_init()
        cmds.extend([
            { "get_tf_chk_drift - refresh": f'({self.base_cmd} refresh' },
            { "get_tf_chk_drift - check changes": f'({self.base_cmd} plan -detailed-exitcode' }
        ])

        return cmds
