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

from config0_publisher.utilities import print_json
from config0_publisher.cloud.aws.codebuild import CodebuildResourceHelper
from config0_publisher.resource.aws import AWSBaseBuildParams

class CodebuildParams(AWSBaseBuildParams):

    def __init__(self,**kwargs):


        AWSBaseBuildParams.__init__(self,**kwargs)

        self.classname = "CodebuildParams"
        self.codebuild_basename = kwargs.get("codebuild_basename","config0-iac")
        self.codebuild_role = kwargs.get("codebuild_role",
                                         "config0-assume-poweruser")
    def _get_tf_direct(self):

        contents = '''
  install:
    commands:
      - which zip || apt-get update
      - which zip || apt-get install -y unzip zip
      - cd $TMPDIR
      - aws s3 cp {loc} terraform.zip --quiet || export DNE="True"
      - if [ ! -z "$DNE" ]; then echo "downloading tf {ver} from hashicorp"; fi
      - if [ ! -z "$DNE" ]; then curl -L -s https://releases.hashicorp.com/terraform/{ver}/terraform_{ver}_linux_amd64.zip -o terraform.zip; fi
      - if [ ! -z "$DNE" ]; then aws s3 cp terraform.zip {loc} --quiet ; fi
      - unzip terraform.zip
      - mv terraform /usr/local/bin/terraform
'''.format(loc=self.tf_bucket_path,
           ver=self.tf_version)

        return contents

    def _get_tf_from_docker_image(self):

        contents = '''
  install:
    commands:
      - docker run --name temp-copy-image -d --entrypoint /bin/sleep {} 900
      - docker cp temp-copy-image:/bin/terraform /usr/local/bin/terraform
      - docker rm -fv temp-copy-image
      - terraform --version
'''.format(self.build_env_vars["DOCKER_IMAGE"])

        return contents

    def _set_inputargs(self):

        self.buildparams = {
            "buildspec": self.get_buildspec(),
            "remote_stateful_bucket": self.remote_stateful_bucket,
            "codebuild_basename": self.codebuild_basename,
            "aws_region": self.aws_region,
            "build_timeout": self.build_timeout,
            "method": self.method
        }

        if self.build_env_vars:
            self.buildparams["build_env_vars"] = self.build_env_vars

        return self.buildparams

    def get_init_contents(self):

        contents = '''
version: 0.2

env:
  variables:
    TMPDIR: /tmp
'''
        if self.ssm_name:
            ssm_params_content = '''
  parameter-store:
    SSM_VALUE: $SSM_NAME
'''
            contents = contents + ssm_params_content

        final_contents = '''
phases:
'''
        contents = contents + final_contents

        return contents

    def _get_install_tf(self,source="direct"):

        if source == "direct":
            return self._get_tf_direct()

        return self._get_tf_from_docker_image()

    def _init_codebuild_helper(self):

        self._set_inputargs()


        self.codebuild_helper = CodebuildResourceHelper(**self.buildparams)

    def submit(self,**inputargs):

        self._init_codebuild_helper()
        self.codebuild_helper.submit(**inputargs)

        return self.codebuild_helper.results

    def retrieve(self,**inputargs):

        # get results from phase json file
        # which should be set
        self.codebuild_helper = CodebuildResourceHelper(**self.phases_info)
        self.codebuild_helper.retrieve(**inputargs)

        return self.codebuild_helper.results

    def run(self,**inputargs):

        self._init_codebuild_helper()


        # testtest456
        print("n0"*32)
        print(inputargs)
        print("n1"*32)
        raise Exception("n4"*32)
        self.codebuild_helper.run(**inputargs)

        return self.codebuild_helper.results

class Codebuild(CodebuildParams):

    def __init__(self,**kwargs):

        self.classname = "Codebuild"

        CodebuildParams.__init__(self,
                                 **kwargs)

    def _get_codebuildspec_prebuild(self):

        contents = '''
  pre_build:
    on-failure: ABORT
    commands:
      - aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID $TMPDIR/$STATEFUL_ID.tar.gz --quiet
      - mkdir -p $TMPDIR/build
      - tar xfz $TMPDIR/$STATEFUL_ID.tar.gz -C $TMPDIR/build
      - rm -rf $TMPDIR/$STATEFUL_ID.tar.gz
'''
        if self.ssm_name:
            ssm_params_content = '''
      - echo $SSM_VALUE | base64 -d > exports.env && chmod 755 exports.env
      - . ./exports.env 
'''
            contents = contents + ssm_params_content

        return contents

    def _get_codebuildspec_build(self):

        if self.method == "create":

            contents = '''
  build:
    on-failure: ABORT
    commands:
      - cd $TMPDIR/build/$APP_DIR
      - /usr/local/bin/terraform init
      - /usr/local/bin/terraform plan -out=tfplan
      - /usr/local/bin/terraform apply tfplan || export FAILED=true
      - if [ ! -z "$FAILED" ]; then /usr/local/bin/terraform destroy -auto-approve; fi
      - if [ ! -z "$FAILED" ]; then echo "terraform apply failed - destroying and exiting with failed" && exit 9; fi
'''
        elif self.method == "destroy":

            contents = '''
  build:
    on-failure: ABORT
    commands:
      - cd $TMPDIR/build/$APP_DIR
      - /usr/local/bin/terraform init
      - /usr/local/bin/terraform destroy -auto-approve
'''
        else:
            raise Exception("method needs to be create/destroy")

        return contents

    def _get_codebuildspec_postbuild(self):

        contents = '''
  post_build:
    commands:
      - cd $TMPDIR/build
      - tar cfz $TMPDIR/$STATEFUL_ID.tar.gz .
      - aws s3 cp $TMPDIR/$STATEFUL_ID.tar.gz s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID --quiet
      - rm -rf $TMPDIR/$STATEFUL_ID.tar.gz
      - echo "# terraform files uploaded s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID"

'''
        return contents

    def get_buildspec(self):

        init_contents = self.get_init_contents()
        install_tf = self._get_install_tf()
        prebuild = self._get_codebuildspec_prebuild()
        build = self._get_codebuildspec_build()
        postbuild = self._get_codebuildspec_postbuild()

        if self.method == "create":
            contents = init_contents + install_tf + prebuild + build + postbuild
        else:
            contents = init_contents + install_tf + prebuild + build  # if destroy, we skip postbuild

        return contents