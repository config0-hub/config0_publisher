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

        #     'rm -rf $TMPDIR/config0 > /dev/null 2>&1 || echo "$TMPDIR/config0 does not exists"',
        cmds = [
            '[ ! -e $TMPDIR/config0 ] || rm -rf $TMPDIR/config0',
            'mkdir -p $TMPDIR/config0/$STATEFUL_ID/build'
        ]

        return cmds

    def get_tf_install(self,tf_bucket_path,tf_version="1.3.7"):

        tf_name = "terraform"
        f_dne = '$TMPDIR/{}.download'.format(tf_name)
        dl_dir = '$TMPDIR/downloads'

        cmds = [ 
            f'[[ ! -e {dl_dir} ]] || (for file in {dl_dir}/{tf_name}_*; do [[ $file != "{dl_dir}/{tf_name}_{tf_version}" ]] && echo "Deleting file: $file" && rm "$file" || echo "could not remove $file" ; done)',
            f'[ ! -e {dl_dir} ] && mkdir -p {dl_dir}',
            f' ls {dl_dir}',
            f' ls {dl_dir}',
            f' ls {dl_dir}',
            f' ls {dl_dir}',
            f'touch "{f_dne}"',
            f'[[ ! -e "{dl_dir}/{tf_name}_{tf_version}" ]] || echo "exists 1" && exit" 9',
            f'[[ ! -e "$TF_PATH" ]] || (rm -rf "{f_dne}" || echo "exists 2" && exit 9',
            f'[[ ! -e "{dl_dir}/{tf_name}_{tf_version}" ]] || rm -rf "{f_dne}"',
            f'[[ ! -e "$TF_PATH" ]] || (rm -rf "{f_dne}" || echo "{f_dne} already removed")'
            ]

        if self.runtime_env == "codebuild":
            cmds.extend([
              'which zip > /dev/null 2>&1 || (apt-get update && apt-get install -y unzip zip)',
            ])

        if tf_bucket_path:

            cmds.extend([
                f'([[ ! -e {f_dne} ]] || (aws s3 cp {tf_bucket_path} {dl_dir}/{tf_name}_{tf_version} --quiet ) && rm -rf {f_dne})'
            ])

        cmds.extend([
            f'[[ ! -e {f_dne} ]] || echo "downloading from source"',
            f'[[ ! -e {f_dne} ]] || (cd {dl_dir} && curl -L -s https://releases.hashicorp.com/{tf_name}/{tf_version}/{tf_name}_{tf_version}_linux_amd64.zip -o {tf_name}_{tf_version})',
            f'[[ ! -e {f_dne} ]] || (aws s3 cp {dl_dir}/{tf_name}_{tf_version} {tf_bucket_path} --quiet && rm -rf {f_dne})'
        ])

        cmds.extend([
            f'[[ ! -e {f_dne} ]] || (echo "CRITICAL: download {tf_name}_{tf_version} failed!" && exit 9)'
        ])

        cmds.extend([
            f'cd {dl_dir} && unzip {tf_name}_{tf_version} && mv {tf_name} $TF_PATH',
            f'ls $TF_PATH',
            f'[[ ! -e $TF_PATH ]] && (cd {dl_dir} && unzip {tf_name}_{tf_version} && mv {tf_name} $TF_PATH > /dev/null)',
            f'[[ ! -e $TF_PATH ]] && exit 8',
            'chmod 777 $TF_PATH'
            ]
        )

        return cmds

    def get_decrypt_buildenv_vars(self,openssl=True):

        envfile_env = os.path.join(self.app_dir,
                                   self.envfile)

        if openssl:
            cmds = [
                f'rm -rf $TMPDIR/config0/$STATEFUL_ID/{envfile_env} || echo "env file already removed"',
                f'if [ -f $TMPDIR/config0/$STATEFUL_ID/build/{envfile_env}.enc ]; then cat $TMPDIR/config0/$STATEFUL_ID/build/{envfile_env}.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:$STATEFUL_ID -base64 | base64 -d > $TMPDIR/config0/$STATEFUL_ID/{self.envfile}; fi'
             ]

        else:
            cmds = [
                f'rm -rf $TMPDIR/config0/$STATEFUL_ID/{envfile_env} || echo "env file already removed"',
                f'/tmp/decrypt -s $STATEFUL_ID -d $TMPDIR/config0/$STATEFUL_ID/{self.envfile} -e $TMPDIR/config0/$STATEFUL_ID/build/{envfile_env}.enc',
                f'([[ -n "$SSM_NAME" ]] && ssm_get -name $SSM_NAME -file $TMPDIR/config0/$STATEFUL_ID/{self.envfile} && cat $TMPDIR/config0/$STATEFUL_ID/{self.envfile}) || echo "ssm_name not given/downloaded"'
            ]

            # for lambda function, we use the ssm_get python cli

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

        #'DIRECTORY="$TMPDIR/config0"; for dir in "$DIRECTORY"/*/; do [[ "$dir" != "$DIRECTORY/$STATEFUL_ID/" ]] && echo "Deleting directory: $dir" && rm -rf "$dir"; done'
        #'rm -rf $TMPDIR/config0/$STATEFUL_ID/build || echo "stateful already removed"',

        cmds = self.reset_dirs()

        cmds.extend([ 'echo "remote bucket s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID"',
                 'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID $TMPDIR/config0/$STATEFUL_ID/$STATEFUL_ID.zip --quiet',
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

        self.tf_version = self.build_env_vars.get("TF_VERSION","1.5.4")
        self._set_tmp_tf_bucket_loc()

    def _set_tmp_tf_bucket_loc(self):

        try:
            self.tmp_bucket = self.build_env_vars["TMP_BUCKET"]
        except:
            self.tmp_bucket = os.environ.get("TMP_BUCKET")

        if not self.tmp_bucket:
            return

        self.tf_bucket_key = f"downloads/terraform/{self.tf_version}"
        self.tf_bucket_path = f"s3://{self.tmp_bucket}/{self.tf_bucket_key}"
