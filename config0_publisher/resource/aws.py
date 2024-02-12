#!/usr/bin/env python

import os

class TFCmdOnAWS(object):
    def __init__(self,**kwargs):

        self.classname = "TFCmdOnAWS"
        self.runtime_env = kwargs["runtime_env"]
        self.run_share_dir = kwargs["run_share_dir"]
        self.app_dir = kwargs["app_dir"]
        self.envfile = kwargs["envfile"]

    def reset_dirs(self):

        cmds = [
            f'rm -rf $TMPDIR/config0 || echo "config0 already removed"',
            f'mkdir -p $TMPDIR/config0',
            'mkdir -p $TMPDIR/config0/$STATEFUL_ID/build'
        ]

        return cmds

    def get_tf_install(self,tf_bucket_path,tf_version="1.3.7"):

        if self.runtime_env == "codebuild":
            cmds = [
              'which zip || apt-get update',
              'which zip || apt-get install -y unzip zip',
            ]
        else:
            cmds = [f'echo "downloading terraform {tf_version}"']

        if tf_bucket_path:
            cmds.extend([
                f'mkdir -p $TMPDIR/downloads || echo "download directory exists"',
                f'([ ! -f "$TMPDIR/downloads/terraform_{tf_version}" ] && aws s3 cp {tf_bucket_path} $TMPDIR/downloads/terraform_{tf_version} --quiet ) || (cd $TMPDIR/downloads && curl -L -s https://releases.hashicorp.com/terraform/{tf_version}/terraform_{tf_version}_linux_amd64.zip -o terraform_{tf_version} && aws s3 cp terraform_{tf_version} {tf_bucket_path} --quiet)'
            ])
        else:
            cmds.extend([
                f'mkdir -p $TMPDIR/downloads || echo "download directory exists"',
                f'cd $TMPDIR/downloads && curl -L -s https://releases.hashicorp.com/terraform/{tf_version}/terraform_{tf_version}_linux_amd64.zip -o terraform_{tf_version} && aws s3 cp terraform_{tf_version} {tf_bucket_path} --quiet'
            ])

        cmds.extend([
            f'(cd $TMPDIR/downloads && unzip terraform_{tf_version} && mv terraform $TF_PATH > /dev/null) || exit 0',
            'chmod 777 $TF_PATH'
            ]
        )

        return cmds
    def get_decrypt_buildenv_vars(self,openssl=True):

        if openssl:
            envfile_env = os.path.join(self.run_share_dir,
                                       self.app_dir,
                                       self.envfile)

            cmds = [
                f'rm -rf {envfile_env} || echo "env file already removed"',
                f'if [ -f {envfile_env}.enc ]; then cat {envfile_env}.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:$STATEFUL_ID -base64 | base64 -d > $TMPDIR/config0/$STATEFUL_ID/{self.envfile}; fi'
             ]

        else:
            envfile_env = os.path.join(self.app_dir,
                                       self.envfile)

            cmds = [
                f'rm -rf $TMPDIR/config0/$STATEFUL_ID/{envfile_env} || echo "env file already removed"',
                f'/tmp/decrypt -s $STATEFUL_ID -d $TMPDIR/config0/$STATEFUL_ID/{self.envfile} -e $TMPDIR/config0/$STATEFUL_ID/build/{envfile_env}.enc'
            ]

        cmds.append(f'(ssm_get -name $SSM_NAME -file $TMPDIR/config0/$STATEFUL_ID/{self.envfile} && cat $TMPDIR/config0/$STATEFUL_ID/{self.envfile}) || echo "ssm_name not specified"')

        return cmds

    def get_src_buildenv_vars(self):

        cmds = [
            f'(if [ -f /$TMPDIR/config0/$STATEFUL_ID/{self.envfile} ]; then cd /$TMPDIR/config0/$STATEFUL_ID/; . ./{self.envfile} ; fi)'
        ]

        #'echo "$TMPDIR/config0/$STATEFUL_ID"'

        return cmds

    def local_to_s3(self):

        # this does not work in lambda
        # so we won't use it for now
        cmds = [
          '(cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate terraform-tfstate) || echo "s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate does not exists"',
          'cd $TMPDIR/config0/$STATEFUL_ID/build && zip -r $TMPDIR/config0/$STATEFUL_ID.zip . ',
          'cd $TMPDIR/config0/$STATEFUL_ID/build && aws s3 cp $TMPDIR/config0/$STATEFUL_ID.zip s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID',
          'cd $TMPDIR/config0/$STATEFUL_ID/build && rm -rf $TMPDIR/config0/$STATEFUL_ID.zip '
        ]

        return cmds

    def s3_to_local(self):

        cmds = [ 'echo "remote bucket s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID"',
                 'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID $TMPDIR/config0/$STATEFUL_ID/$STATEFUL_ID.zip --quiet',
                 'rm -rf $TMPDIR/config0/$STATEFUL_ID/build || echo "stateful already removed"',
                 'unzip -o $TMPDIR/config0/$STATEFUL_ID/$STATEFUL_ID.zip -d $TMPDIR/config0/$STATEFUL_ID/build',
                 'rm -rf $TMPDIR/config0/$STATEFUL_ID/$STATEFUL_ID.zip'
        ]

        return cmds

    def get_tf_apply(self):

        cmds = [
            f'{self.get_src_buildenv_vars()[0]} && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init',
            f'{self.get_src_buildenv_vars()[0]} && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH plan -out=tfplan',
            f'{self.get_src_buildenv_vars()[0]} && (cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH apply tfplan) || ($TF_PATH destroy -auto-approve && exit 9)'
        ]

        return cmds

    def get_tf_destroy(self):

        #'(cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init) || (cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init --migrate-state  -force-copy)',
        cmds = [
          f'{self.get_src_buildenv_vars()[0]} && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init',
          f'{self.get_src_buildenv_vars()[0]} && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH destroy -auto-approve'
        ]

        return cmds

    def get_tf_validate(self):

        #'(cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init) || (cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init --migrate-state  -force-copy)',
        cmds = [
            f'{self.get_src_buildenv_vars()[0]} && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init',
            f'{self.get_src_buildenv_vars()[0]} && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH refresh',
            f'{self.get_src_buildenv_vars()[0]} && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH plan -detailed-exitcode'
        ]

        return cmds

class AWSBaseBuildParams(object):

    def __init__(self,**kwargs):

        self.classname = "AWSBaseBuildParams"

        self.method = kwargs.get("method","create")

        self.build_timeout = int(kwargs.get("build_timeout",
                                            1800))

        self.aws_region = kwargs.get("aws_region")
        self.phases_info = kwargs.get("phases_info")
        self.build_env_vars = kwargs.get("build_env_vars")
        self.ssm_name = kwargs.get("ssm_name")
        self.remote_stateful_bucket = kwargs.get("remote_stateful_bucket")

        self.aws_role = kwargs.get("aws_role",
                                    "config0-assume-poweruser")

        self.skip_env_vars = ["AWS_SECRET_ACCESS_KEY"]

        if not self.build_env_vars:
            self.build_env_vars = {}

        #self._override_env_var_method()

        self.tf_bucket_key = None
        self.tf_bucket_path = None

        self.tf_version = self.build_env_vars.get("TF_VERSION","1.5.4")
        self._set_tmp_tf_bucket_loc()

    def _set_tmp_tf_bucket_loc(self):

        try:
            self.tmp_bucket = self.build_env_vars["TMP_BUCKET"]
        except:
            self.tmp_bucket = os.environ.get("TMP_BUCKET")

        if self.tmp_bucket:
            self.tf_bucket_key = f"downloads/terraform/{self.tf_version}"
            self.tf_bucket_path = f"s3://{self.tmp_bucket}/{self.tf_bucket_key}"