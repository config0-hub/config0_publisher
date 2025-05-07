#!/usr/bin/env python

import os

class TFAwsBaseBuildParams(object):
    """Base class for AWS Terraform/OpenTofu build parameters."""

    def __init__(self, **kwargs):
        """Initialize build parameters with provided kwargs."""
        self.classname = "TFAwsBaseBuildParams"
        self.method = kwargs.get("method", "create")
        self.build_timeout = int(kwargs.get("build_timeout", 1800))
        self.aws_region = kwargs.get("aws_region")
        self.phases_info = kwargs.get("phases_info")
        self.build_env_vars = kwargs.get("build_env_vars")
        self.ssm_name = kwargs.get("ssm_name")
        self.remote_stateful_bucket = kwargs.get("remote_stateful_bucket")
        self.aws_role = kwargs.get("aws_role", "config0-assume-poweruser")
        self.skip_env_vars = ["AWS_SECRET_ACCESS_KEY"]

        if self.build_env_vars is None:
            self.build_env_vars = {}

        self.app_name = "terraform"

        # Required parameters
        try:
            self.binary = kwargs["binary"]
            self.version = kwargs["version"]
            self.run_share_dir = kwargs["run_share_dir"]
            self.app_dir = kwargs["app_dir"]
        except KeyError as e:
            raise ValueError(f"Missing required parameter: {e}")

        self._set_tmp_tf_bucket_loc()

    def _set_tmp_tf_bucket_loc(self):
        """Set up temporary S3 bucket location for Terraform/OpenTofu binaries."""
        try:
            self.tmp_bucket = self.build_env_vars.get("TMP_BUCKET")
            if self.tmp_bucket is None:
                self.tmp_bucket = os.environ.get("TMP_BUCKET")
        except Exception:
            self.tmp_bucket = os.environ.get("TMP_BUCKET")

        if self.tmp_bucket is None:
            return

        if self.binary in ["opentofu", "tofu"]:
            self.tf_bucket_key = f"downloads/tofu/{self.version}"
        else:
            self.tf_bucket_key = f"downloads/terraform/{self.version}"

        self.tf_bucket_path = f"s3://{self.tmp_bucket}/{self.tf_bucket_key}"