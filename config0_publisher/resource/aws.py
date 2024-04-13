#!/usr/bin/env python

import os

class TFCmdOnAWS(object):
    def __init__(self,**kwargs):

        self.classname = "TFCmdOnAWS"
        self.runtime_env = kwargs["runtime_env"]
        self.run_share_dir = kwargs["run_share_dir"]
        self.app_dir = kwargs["app_dir"]
        self.envfile = kwargs["envfile"]
        self.app_name = "terraform"
        self.dl_subdir = "config0/downloads"

    def reset_dirs(self):

        cmds = [
            f'rm -rf $TMPDIR/config0 > /dev/null 2>&1 || echo "config0 already removed"',
            f'mkdir -p $TMPDIR/config0/$STATEFUL_ID/build',
            f'mkdir -p $TMPDIR/{self.dl_subdir}',
            f'echo "##############"; df -h; echo "##############"'
        ]

        return cmds

    def get_tf_install(self,tf_bucket_path,tf_version="1.3.7"):

        if self.runtime_env == "codebuild":
            cmds = [
              'which zip || apt-get update',
              'which zip || apt-get install -y unzip zip',
            ]
        else:
            cmds = [f'echo "downloading {self.app_name}_{tf_version}"']

        if tf_bucket_path:
            cmds.extend([
                f'([ ! -f "$TMPDIR/{self.dl_subdir}/{self.app_name}_{tf_version}" ] && aws s3 cp {tf_bucket_path} $TMPDIR/{self.dl_subdir}/{self.app_name}_{tf_version} --quiet ) || (cd $TMPDIR/{self.dl_subdir} && curl -L -s https://releases.hashicorp.com/terraform/{tf_version}/{self.app_name}_{tf_version}_linux_amd64.zip -o {self.app_name}_{tf_version} && aws s3 cp {self.app_name}_{tf_version} {tf_bucket_path} --quiet)'
            ])
        else:
            cmds.extend([
                f'cd $TMPDIR/{self.dl_subdir} && curl -L -s https://releases.hashicorp.com/terraform/{tf_version}/{self.app_name}_{tf_version}_linux_amd64.zip -o {self.app_name}_{tf_version} && aws s3 cp {self.app_name}_{tf_version} {tf_bucket_path} --quiet'
            ])

        cmds.extend([
            f'(cd $TMPDIR/{self.dl_subdir} && unzip {self.app_name}_{tf_version} && mv {self.app_name} $TF_PATH > /dev/null) || exit 0',
            'chmod 777 $TF_PATH'
            ]
        )

        return cmds
    def get_decrypt_buildenv_vars(self,openssl=True):

        '''
        # for lambda function, we use the ssm_get python cli
        #'ssm_get -name $SSM_NAME -file $TMPDIR/config0/$STATEFUL_ID/{self.envfile}'
        #'[ -n "$SSM_NAME" ] && echo "SSM_NAME: $SSM_NAME" || echo "SSM_NAME not set"'
        '''

        envfile_env = os.path.join(self.app_dir,
                                   self.envfile)

        if openssl:
            cmds = [
                f'rm -rf $TMPDIR/config0/$STATEFUL_ID/{envfile_env} > /dev/null 2>&1 || echo "env file already removed"',
                f'if [ -f $TMPDIR/config0/$STATEFUL_ID/build/{envfile_env}.enc ]; then cat $TMPDIR/config0/$STATEFUL_ID/build/{envfile_env}.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:$STATEFUL_ID -base64 | base64 -d > $TMPDIR/config0/$STATEFUL_ID/{self.envfile}; fi'
             ]

        else:
            cmds = [
                f'rm -rf $TMPDIR/config0/$STATEFUL_ID/{envfile_env} > /dev/null 2>&1 || echo "env file already removed"',
                f'/tmp/decrypt -s $STATEFUL_ID -d $TMPDIR/config0/$STATEFUL_ID/{self.envfile} -e $TMPDIR/config0/$STATEFUL_ID/build/{envfile_env}.enc',
                f'ssm_get -name $SSM_NAME -file $TMPDIR/config0/$STATEFUL_ID/{self.envfile} || echo "WARNING: \nSSM_NAME: $SSM_NAME\n not set or problems fetching it"'
            ]

        return cmds

    def get_codebuild_ssm_concat(self):

        if not os.environ.get("DEBUG_STATEFUL"):
            return f'echo $SSM_VALUE | base64 -d >> $TMPDIR/config0/$STATEFUL_ID/{self.envfile}'

        return f'echo $SSM_VALUE | base64 -d >> $TMPDIR/config0/$STATEFUL_ID/{self.envfile} && cat $TMPDIR/config0/$STATEFUL_ID/{self.envfile}'

    def get_src_buildenv_vars_cmd(self):
        return f'if [ -f /$TMPDIR/config0/$STATEFUL_ID/{self.envfile} ]; then cd /$TMPDIR/config0/$STATEFUL_ID/; . ./{self.envfile} ; fi'

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

        cmds = self.reset_dirs()

        cmds.extend([
            'echo "remote bucket s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID"',
            'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID $TMPDIR/config0/$STATEFUL_ID/$STATEFUL_ID.zip --quiet',
            'rm -rf $TMPDIR/config0/$STATEFUL_ID/build > /dev/null 2>&1 || echo "stateful already removed"',
            'unzip -o $TMPDIR/config0/$STATEFUL_ID/$STATEFUL_ID.zip -d $TMPDIR/config0/$STATEFUL_ID/build',
            'rm -rf $TMPDIR/config0/$STATEFUL_ID/$STATEFUL_ID.zip'
        ])

        return cmds

    def get_tf_apply(self):

        base_cmd = self.get_src_buildenv_vars_cmd()

        cmds = [
            f'({base_cmd}) && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init',
            f'({base_cmd}) && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH plan -out=tfplan',
            f'({base_cmd}) && (cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH apply tfplan) || ($TF_PATH destroy -auto-approve && exit 9)'
        ]

        return cmds

    def get_tf_destroy(self):

        base_cmd = self.get_src_buildenv_vars_cmd()

        cmds = [
          f'({base_cmd}) && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init',
          f'({base_cmd}) && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH destroy -auto-approve'
        ]

        return cmds

    def get_tf_validate(self):

        base_cmd = self.get_src_buildenv_vars_cmd()

        cmds = [
            f'({base_cmd}) && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH init',
            f'({base_cmd}) && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH refresh',
            f'({base_cmd}) && cd $TMPDIR/config0/$STATEFUL_ID/build/$APP_DIR && $TF_PATH plan -detailed-exitcode'
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

        self.app_name = "terraform"
        self.tf_version = self.build_env_vars.get("TF_VERSION",
                                                  "1.5.4")
        self._set_tmp_tf_bucket_loc()

    def _set_tmp_tf_bucket_loc(self):

        try:
            self.tmp_bucket = self.build_env_vars["TMP_BUCKET"]
        except:
            self.tmp_bucket = os.environ.get("TMP_BUCKET")

        if not self.tmp_bucket:
            return

        self.tf_bucket_key = f"downloads/{self.app_name}/{self.tf_version}"
        self.tf_bucket_path = f"s3://{self.tmp_bucket}/{self.tf_bucket_key}"