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
#Written by Gary Leong  <gary@config0.com, May 11,2019

import os
import json

from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import OnDiskTmpDir
from config0_publisher.resource_manage import ResourceCmdHelper

class DoCli(ResourceCmdHelper):

    def __init__(self,**kwargs):

        ResourceCmdHelper.__init__(self,
                                   app_name="docli")

        self.classname = 'DoCli'
        self.logger = Config0Logger(self.classname)
        self.logger.debug("Instantiating %s" % self.classname)
        self.file_config = None
        self.file_config_loc = None
        self.tempdir = None
        self.resource_tags_keys = [ "tags", 
                                    "name", 
                                    "schedule_id", 
                                    "job_instance_id",
                                    "job_id" ]

        self.get_region()
        self._set_do_token(**kwargs)

    def _set_do_token(self,**kwargs):

        self.do_token = kwargs.get("do_token")

        if not self.do_token and not os.environ.get("DO_TOKEN"):
            msg = 'The DO_TOKEN environmental variables need to be set'
            self.logger.error(msg)
            exit(9)

        if not self.do_token: 
            self.do_token = os.environ["DO_TOKEN"]

    def get_tags(self):

        tags = [ self.do_default_region, 
                 self.product, 
                 self.provider ]

        for key_eval in self.resource_tags_keys:

            if not self.inputargs.get(key_eval): 
                continue

            tags.append(self.inputargs[key_eval])

        return tags

    def set_ondisktmp(self):
        self.tempdir = OnDiskTmpDir()

    def write_file_config(self):

        with open(self.file_config_loc, 'w') as _file:
            _file.write(json.dumps(self.file_config,indent=4))

    def parse_set_env_vars(self,env_vars,upper_case=True):

        self.inputargs = {}

        for env_var in env_vars:

            if not os.environ.get(env_var.upper()): 
                continue

            if env_var == "do_default_region":
                self.inputargs["do_default_region"] = os.environ[env_var.upper()]
            else:
                self.inputargs[env_var] = os.environ[env_var.upper()]

    def get_final_cmd(self,cmd,add_region=True,output_to_json=True,add_token=True):

        if add_region: 
            cmd = "{} --region {}".format(cmd,self.do_default_region)

        if add_token: 
            cmd = "{} -t {}".format(cmd,self.do_token)

        if output_to_json: 
            cmd = "{} --output json".format(cmd)

        return cmd

    def get_region(self):

        try:
            self.do_default_region = self.inputargs.get("do_default_region")
        except:
            self.do_default_region = None

        if not self.do_default_region or self.do_default_region == "None": 
            self.do_default_region = "nyc3"

        self.logger.debug('Region set to "{}"'.format(self.do_default_region))
