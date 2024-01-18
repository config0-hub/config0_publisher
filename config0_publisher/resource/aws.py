#!/usr/bin/env python
#
#Project: config0_publisher: Config0 is a SaaS for building and managing
#software and DevOps automation. This particular packages is a python
#helper for publishing stacks, hostgroups, shellouts/scripts and other
#assets used for automation
#
#Examples include cloud infrastructure, CI/CD, and data analytics
#
#Copyright (C) Gary Leong - All Rights Reserved
#Unauthorized copying of this file, via any medium is strictly prohibited
#Proprietary and confidential
#Written by Gary Leong  <gary@config0.com, May 11,2022

import os
import jinja2
import glob
import json
import boto3

from time import sleep
from time import time

from config0_publisher.cloud.aws.codebuild import CodebuildResourceHelper
from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import print_json
from config0_publisher.utilities import to_json
from config0_publisher.utilities import get_values_frm_json
from config0_publisher.utilities import get_hash
from config0_publisher.shellouts import execute4
from config0_publisher.shellouts import execute3
from config0_publisher.resource.manage import to_jsonfile
#from config0_publisher.shellouts import execute3a

from config0_publisher.serialization import b64_decode
from config0_publisher.serialization import b64_encode
from config0_publisher.variables import SyncClassVarsHelper
from config0_publisher.templating import list_template_files
from config0_publisher.output import convert_config0_output_to_values
from config0_publisher.shellouts import rm_rf

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