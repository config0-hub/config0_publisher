#!/usr/bin/env python
#
#Project: config0-helper: Config0 is a SaaS for building and managing 
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
import json

from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import OnDiskTmpDir
from config0_publisher.resource_manage import ResourceCmdHelper
from config0_publisher.utilities import to_json

class AwsCli(ResourceCmdHelper):

    def __init__(self,**kwargs):

        ResourceCmdHelper.__init__(self,
                                   app_name="awscli")

        self.classname = 'AwsCli'
        self.logger = Config0Logger(self.classname)
        self.logger.debug("Instantiating %s" % self.classname)
        self.file_config = None
        self.file_config_loc = None
        self.tempdir = None
        self.resource_tags_keys = [ "name", 
                                    "schedule_id", 
                                    "job_instance_id",
                                    "job_id" ]

    def get_tags(self):

        tags = [ self.aws_default_region, 
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

    def _get_add_tags(self):

        try:
            add_tags = to_json(self.inputargs.get("tags"))
        except:
            add_tags = None

        if not add_tags: return 
  
        return add_tags

    def get_resource_tags(self,**kwargs):

        name = kwargs.get("name")
        if not name: name = self.inputargs.get("name")
        
        tags = "["
        if name: tags = tags + "{"+"Key={},Value={}".format("Name",name)+"}"
        
        for key_eval in self.resource_tags_keys:

            if not self.inputargs.get(key_eval): 
                continue

            tags = tags + ",{"+"Key={},Value={}".format(key_eval,
                                                        self.inputargs[key_eval])+"}"

        add_tags = self._get_add_tags()

        if not add_tags:
            tags = tags + "]"
            return tags

        for _k,_v in add_tags.items():
            tags = tags + ",{"+"Key={},Value={}".format(_k,_v)+"}"

        tags = tags + "]"

        return tags

    def get_cmd_region(self,cmd):

        return "{} --region {}".format(cmd,
                                       self.aws_default_region)

    def get_region(self):

        self.aws_default_region = self.inputargs.get("aws_default_region")

        if not self.aws_default_region:
            self.aws_default_region = "us-east-1"

        if self.aws_default_region == "None": 
            self.aws_default_region = "us-east-1"

        self.logger.debug('Region set to "{}"'.format(self.aws_default_region))
