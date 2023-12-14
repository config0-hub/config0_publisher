#!/usr/bin/env python

import logging
import re
import os
import boto3
import gzip
from io import BytesIO
from time import sleep
from time import time

from config0_publisher.loggerly import Config0Logger

class SetClassVarsHelper:

    def __init__(self,set_env_vars=None,kwargs=None,env_vars=None,set_default_null=None):

        if set_env_vars:
            self.set_env_vars = set_env_vars
        else:
            self.set_env_vars = None

        self.kwargs = kwargs

        self.env_vars = env_vars

        if not self.env_vars:
            self.env_vars = {}

        self.set_default_null = set_default_null

    def set_class_vars_srcs(self):

        if not self.set_env_vars:
            return

        for env_var,must_exists in self.set_env_vars.items():

            if env_var in self.kwargs:
                exec('self.{}="{}"'.format(env_var,
                                         self.kwargs[env_var]))
                continue

            if env_var.upper() in self.env_vars:
                exec('self.{}="{}"'.format(env_var,
                                           self.env_vars[env_var.upper()]))
                continue

            if must_exists:
                raise Exception("variable {} needs to be set".format(env_var))

            if self.set_default_null:
                self.logger.debug("set None for variable {}".format(env_var))
                exec('self.{}=None'.format(env_var))
