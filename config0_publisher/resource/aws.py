#!/usr/bin/env python

class TFCmdOnAWS(object):
    def __init__(self,runtime_env="codebuild"):

        self.classname = "TFCmdOnAWS"
        self.runtime_env = runtime_env

    def get_tf_install(self,tf_bucket_path,tf_version="1.3.7"):

        if self.runtime_env == "codebuild":
            cmds = [
              'which zip || apt-get update',
              'which zip || apt-get install -y unzip zip',
            ]
        else:
            cmds = []

        cmds.extend([
            'cd $TMPDIR',
            f'aws s3 cp {tf_bucket_path} terraform.zip --quiet || export DNE="True"',
            f'if [ ! -z "$DNE" ]; then echo "downloading tf {tf_version} from hashicorp"; fi',
            f'if [ ! -z "$DNE" ]; then curl -L -s https://releases.hashicorp.com/terraform/{tf_version}/terraform_{tf_version}_linux_amd64.zip -o terraform.zip; fi',
            f'if [ ! -z "$DNE" ]; then aws s3 cp terraform.zip {tf_bucket_path} --quiet ; fi',
            'unzip terraform.zip',
            'mv terraform $TF_PATH'
        ])

        return cmds
    def get_decrypt_buildenv_vars(self):

        cmds = [
            'export ENVFILE_ENC=$TMPDIR/build/$APP_DIR/build_env_vars.env.enc',
            'if [ -f "$ENVFILE_ENC" ]; then cat $ENVFILE_ENC | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:$STATEFUL_ID -base64 | base64 -d > $TMPDIR/build_env_vars.env; fi',
            'echo "#######################################" && cat $TMPDIR/build_env_vars.env && echo "#######################################"'  # testtest456
        ]

        return cmds

    def get_src_buildenv_vars(self):

        cmds = [
            'if [ -f /$TMPDIR/build_env_vars.env ]; then cd /$TMPDIR; . ./build_env_vars.env ; fi'
        ]

        return cmds

    def local_to_s3(self):

        cmds = [
          'cd $TMPDIR/build',
          'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate $APP_DIR/terraform-tfstate --quiet || echo "s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID.tfstate does not exists"',
          'tar cfz $TMPDIR/$STATEFUL_ID.tar.gz . ',
          'aws s3 cp $TMPDIR/$STATEFUL_ID.tar.gz s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID --quiet ',
          'rm -rf $TMPDIR/$STATEFUL_ID.tar.gz ',
          'echo "# terraform files uploaded s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID" '
        ]

        return cmds

    def s3_to_local(self):

        cmds = [ 'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID $TMPDIR/$STATEFUL_ID.tar.gz --quiet',
                 'mkdir -p $TMPDIR/build',
                 'tar xfz $TMPDIR/$STATEFUL_ID.tar.gz -C $TMPDIR/build',
                 'rm -rf $TMPDIR/$STATEFUL_ID.tar.gz'
        ]

        return cmds

    def get_tf_apply(self):

        cmds = [
            'cd $TMPDIR/build/$APP_DIR',
            '$TF_PATH init',
            '$TF_PATH plan -out=tfplan',
            '$TF_PATH apply tfplan || export FAILED=true',
            'if [ ! -z "$FAILED" ]; then $TF_PATH destroy -auto-approve; fi',
            'if [ ! -z "$FAILED" ]; then echo "terraform apply failed - destroying and exiting with failed" && exit 9; fi'
        ]

        return cmds

    def get_tf_destroy(self):

        cmds = [
          'cd $TMPDIR/build/$APP_DIR',
          '$TF_PATH init',
          '$TF_PATH destroy -auto-approve'
        ]

        return cmds

    def _test_get_with_buildspec(self):

        contents = '''version: 0.2
phases:
  install:
    commands:
      - echo "Installing system dependencies..."
      - apt-get update && apt-get install -y zip
  pre_build:
    commands:
      - aws s3 cp s3://app-env.tmp.williaumwu.eee71/meelsrivavqqdkzy /tmp/meelsrivavqqdkzy.tar.gz --quiet
      - mkdir -p /var/tmp/share/meelsrivavqqdkzy
      - tar xfz /tmp/meelsrivavqqdkzy.tar.gz -C /var/tmp/share/meelsrivavqqdkzy/
      - rm -rf /tmp/meelsrivavqqdkzy.tar.gz
      - echo "Creating a virtual environment..."
      - cd /var/tmp/share/meelsrivavqqdkzy && python3 -m venv venv
  build:
    commands:
      - export PYTHON_VERSION=`python -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"`
      - cd /var/tmp/share/meelsrivavqqdkzy
      - . venv/bin/activate
      - echo "Installing project dependencies..."
      - pip install -r src/requirements.txt
      - cp -rp src/* venv/lib/python$PYTHON_VERSION/site-packages/
  post_build:
    commands:
      - cd /var/tmp/share/meelsrivavqqdkzy
      - cd venv/lib/python$PYTHON_VERSION/site-packages/
      - zip -r /tmp/trigger-codebuild.zip .
      - aws s3 cp /tmp/trigger-codebuild.zip s3://codebuild-shared-ed-eval-d645633/trigger-codebuild.zip

'''
        return contents

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
            self.tmp_bucket = None

        if self.tmp_bucket:
            self.tf_bucket_key = f"downloads/terraform/{self.tf_version}"
            self.tf_bucket_path = f"s3://{self.tmp_bucket}/{self.tf_bucket_key}"

    # 123
    def _set_tf_version(self):

        try:
            self.tf_version = self.build_env_vars["DOCKER_IMAGE"].split(":")[-1]
        except:
            self.tf_version = "1.5.4"

    def _override_env_var_method(self):

        if not self.build_env_vars.get("METHOD"):
            return

        if self.method == "destroy":
            self.build_env_vars["METHOD"] = "destroy"
        elif self.method == "create":
            self.build_env_vars["METHOD"] = "create"