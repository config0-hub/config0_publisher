#!/usr/bin/env python

import os

class TFCmdOnAWS(object):
    def __init__(self,**kwargs):

        self.classname = "TFCmdOnAWS"
        self.runtime_env = kwargs["runtime_env"]
        self.run_share_dir = kwargs["run_share_dir"]
        self.app_dir = kwargs["app_dir"]
        self.envfile = kwargs["envfile"]

    def get_tf_install(self,tf_bucket_path,tf_version="1.3.7"):

        if self.runtime_env == "codebuild":
            cmds = [
              'which zip || apt-get update',
              'which zip || apt-get install -y unzip zip',
            ]
        else:
            cmds = []

        #f'aws s3 cp {tf_bucket_path} terraform.zip --quiet || export DNE="True"',

        if tf_bucket_path:
            cmds.extend([
                f'(cd $TMPDIR && aws s3 cp {tf_bucket_path} terraform.zip --quiet) || export DNE="True"',
                f'if [ ! -z "$DNE" ]; then cd $TMPDIR && echo "downloading tf {tf_version} from hashicorp"; fi',
                f'if [ ! -z "$DNE" ]; then cd $TMPDIR && curl -L -s https://releases.hashicorp.com/terraform/{tf_version}/terraform_{tf_version}_linux_amd64.zip -o terraform.zip; fi',
                f'if [ ! -z "$DNE" ]; then cd $TMPDIR && aws s3 cp terraform.zip {tf_bucket_path} --quiet ; fi'
            ])
        else:
            cmds.extend([
                f'cd $TMPDIR && export DNS=True && if [ ! -z "$DNE" ]; then curl -L -s https://releases.hashicorp.com/terraform/{tf_version}/terraform_{tf_version}_linux_amd64.zip -o terraform.zip; fi'
            ])

        # testtest456
        #cmds = [ f'cd $TMPDIR && export DNS=True && if [ ! -z "$DNE" ]; then curl -L -s https://releases.hashicorp.com/terraform/{tf_version}/terraform_{tf_version}_linux_amd64.zip -o $TMPDIR/terraform.zip; fi',
        #         'ls -al $TMPDIR']

        cmds.extend([
            'cd $TMPDIR && unzip terraform.zip',
            'cd $TMPDIR && mv terraform $TF_PATH > /dev/null || exit 0',
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
                 f'if [ -f {envfile_env}.enc ]; then cat {envfile_env}.enc | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:$STATEFUL_ID -base64 | base64 -d > $TMPDIR/{self.envfile}; fi',
                 f'echo "#######################################" && cat $TMPDIR/{self.envfile} && echo "#######################################"'  # testtest456
             ]
        else:
            envfile_env = os.path.join(self.app_dir,
                                       self.envfile)
            cmds = [
                f'/tmp/decrypt -s $STATEFUL_ID -d $TMPDIR/{self.envfile} -e $TMPDIR/build/{envfile_env}.enc',
                f'echo "#######################################" && cat $TMPDIR/{self.envfile} && echo "#######################################"'
                # testtest456
            ]

        return cmds

    def get_src_buildenv_vars(self):

        cmds = [
            f'if [ -f /$TMPDIR/{self.envfile} ]; then cd /$TMPDIR; . ./{self.envfile} ; fi'
        ]

        return cmds

    def local_to_s3(self):

        #'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate $APP_DIR/terraform-tfstate --quiet || echo "s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate does not exists"',
        cmds = [
          'cd $TMPDIR/build && aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate $APP_DIR/terraform-tfstate --quiet',
          'cd $TMPDIR/build && zip -r $TMPDIR/$STATEFUL_ID.zip . ',
          'cd $TMPDIR/build && aws s3 cp $TMPDIR/$STATEFUL_ID.zip s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID --quiet ',
          'cd $TMPDIR/build && rm -rf $TMPDIR/$STATEFUL_ID.zip ',
          'echo "# terraform files uploaded s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID" '
        ]

        return cmds

    def s3_to_local(self):

        cmds = [ 'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID $TMPDIR/$STATEFUL_ID.zip --quiet',
                 'mkdir -p $TMPDIR/build',
                 'unzip -o $TMPDIR/$STATEFUL_ID.zip -d $TMPDIR/build',
                 'rm -rf $TMPDIR/$STATEFUL_ID.zip'
        ]

        return cmds

    def get_tf_apply(self):

        cmds = [
            'cd $TMPDIR/build/$APP_DIR && cat backend.tf',
            'cd $TMPDIR/build/$APP_DIR && $TF_PATH init',
            'cd $TMPDIR/build/$APP_DIR && $TF_PATH plan -out=tfplan',
            'cd $TMPDIR/build/$APP_DIR && $TF_PATH apply tfplan || export FAILED=true',
            'cd $TMPDIR/build/$APP_DIR && if [ ! -z "$FAILED" ]; then cd $TMPDIR/build/$APP_DIR && $TF_PATH destroy -auto-approve; fi',
            'cd $TMPDIR/build/$APP_DIR && if [ ! -z "$FAILED" ]; then echo "terraform apply failed - destroying and exiting with failed" && exit 9; fi'
        ]

        return cmds

    def get_tf_destroy(self):

        cmds = [
          'cd $TMPDIR/build/$APP_DIR',
          'cd $TMPDIR/build/$APP_DIR && $TF_PATH init',
          'cd $TMPDIR/build/$APP_DIR && $TF_PATH destroy -auto-approve'
        ]

        return cmds

    def get_tf_validate(self):

        cmds = [
            'cd $TMPDIR/build/$APP_DIR',
            'cd $TMPDIR/build/$APP_DIR && $TF_PATH init',
            'cd $TMPDIR/build/$APP_DIR && $TF_PATH refresh',
            'cd $TMPDIR/build/$APP_DIR && $TF_PATH plan -detailed-exitcode'
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

        self._override_env_var_method()

        self.tf_bucket_key = None
        self.tf_bucket_path = None

        self._set_tf_version()
        self._set_tmp_tf_bucket_loc()

    def _set_tmp_tf_bucket_loc(self):

        try:
            self.tmp_bucket = self.build_env_vars["TMP_BUCKET"]
        except:
            self.tmp_bucket = os.environ.get("TMP_BUCKET")

        if self.tmp_bucket:
            self.tf_bucket_key = f"downloads/terraform/{self.tf_version}"
            self.tf_bucket_path = f"s3://{self.tmp_bucket}/{self.tf_bucket_key}"

    # 123
    def _set_tf_version(self):

        try:
            self.tf_version = self.build_env_vars["DOCKER_IMAGE"].split(":")[-1]
        except:
            self.tf_version = "1.5.4"

    # testtest456
    # is this needed?
    def _override_env_var_method(self):

        if not self.build_env_vars.get("METHOD"):
            return

        if self.method == "destroy":
            self.build_env_vars["METHOD"] = "destroy"
        elif self.method == "create":
            self.build_env_vars["METHOD"] = "create"