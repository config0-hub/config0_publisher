#!/usr/bin/env python

import re
import gzip
import traceback
from io import BytesIO
from time import time
from config0_publisher.cloud.aws.common import AWSCommonConn

class CodebuildResourceHelper(AWSCommonConn):
    DEFAULT_CONFIG = {
        "build_image": "aws/codebuild/standard:7.0",
        "image_type": "LINUX_CONTAINER",
        "compute_type": "BUILD_GENERAL1_SMALL",
        "codebuild_project": "config0-iac"
    }

    ENV_VARS = {
        "tmp_bucket": True,
        "log_bucket": True,
        "build_image": True,
        "image_type": True,
        "compute_type": True,
        "codebuild_project": True,
        "app_dir": None,
        "stateful_id": None,
        "remote_stateful_bucket": None,
        "run_share_dir": None,
        "share_dir": None
    }

    SKIP_KEYS = ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"]
    SPARSE_KEYS = ["STATEFUL_ID", "REMOTE_STATEFUL_BUCKET", "TMPDIR", "APP_DIR", "SSM_NAME"]

    def __init__(self, **kwargs):
        self.buildspec = kwargs.get("buildspec")
        self.build_id = None
        self.logarn = None
        self.output = None
        self.build_timeout = kwargs.get("build_timeout", 3600)
        self.build_expire_at = int(time()) + self.build_timeout
        self.build_env_vars = kwargs.get("build_env_vars", {})
        self.s3_output_key = kwargs.get("s3_output_key")

        if "set_env_vars" in kwargs:
            kwargs["set_env_vars"] = self.ENV_VARS

        AWSCommonConn.__init__(self,
                               default_values=self.DEFAULT_CONFIG,
                               **kwargs)

        self.codebuild_client = self.session.client('codebuild')
        
        # Set default values if not provided in inputargs
        for key in ["build_image", "image_type", "compute_type", "codebuild_project"]:
            if not self.results["inputargs"].get(key):
                self.results["inputargs"][key] = getattr(self, key)

    def _get_env_vars(self, sparse=True):
        env_vars = {}
        _added = []

        if not self.build_env_vars:
            return env_vars

        pattern = r"^CODEBUILD"

        for _k, _v in self.build_env_vars.items():
            if not _v:
                self.logger.debug(f"env var {_k} is empty/None - skipping")
                continue

            if _k in self.SKIP_KEYS:
                continue

            if sparse and _k not in self.SPARSE_KEYS:
                continue

            if re.search(pattern, _k):
                continue

            if _k in _added:
                continue

            _added.append(_k)
            env_vars[_k] = _v

        env_vars.update({
            "BUILD_EXPIRE_AT":str(int(self.build_expire_at)),
            "OUTPUT_BUCKET": self.tmp_bucket,
            "OUTPUT_BUCKET_KEY": self.s3_output_key
        })

        return env_vars

    def get_base_event(self, sparse_env_vars=True):

        timeout = max(1, int(self.build_timeout/60))

        event = {
            "codebuild_project_name": self.codebuild_project,
            "env_vars_override": self._get_env_vars(sparse=sparse_env_vars),
            "timeout_override": self.build_timeout,
            "expiry_minutes": timeout,
            "image_override": self.build_image,
            "compute_type_override": self.compute_type,
            "environment_type_override": self.imaget_type,
        }

        if self.buildspec:
            event["buildspec_override"] = self.buildspec

        return event

