#!/usr/bin/env python

import os

class TFAwsBaseBuildParams(object):

    def __init__(self,**kwargs):

        self.classname = "TFAwsBaseBuildParams"

        self.method = kwargs.get("method","create")

        self.build_timeout = int(kwargs.get("build_timeout",
                                            1800))

        self.aws_region = kwargs.get("aws_region")
        self.build_env_vars = kwargs.get("build_env_vars")
        self.ssm_name = kwargs.get("ssm_name")
        self.remote_stateful_bucket = kwargs.get("remote_stateful_bucket")

        self.aws_role = kwargs.get("aws_role",
                                    "config0-assume-poweruser")

        self.skip_env_vars = ["AWS_SECRET_ACCESS_KEY"]

        if not self.build_env_vars:
            self.build_env_vars = {}

        self.app_name = "terraform"

        self.binary = kwargs["binary"]
        self.version = kwargs["version"]

        self.run_share_dir = kwargs["run_share_dir"]
        self.app_dir = kwargs["app_dir"]

        self._set_tmp_tf_bucket_loc()

    def _set_tmp_tf_bucket_loc(self):

        try:
            self.tmp_bucket = self.build_env_vars["TMP_BUCKET"]
        except:
            self.tmp_bucket = os.environ.get("TMP_BUCKET")

        if not self.tmp_bucket:
            return

        if self.binary in ["opentofu", "tofu"]:
            self.tf_bucket_key = f"downloads/tofu/{self.version}"
        else:
            self.tf_bucket_key = f"downloads/terraform/{self.version}"

        self.tf_bucket_path = f"s3://{self.tmp_bucket}/{self.tf_bucket_key}"