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
#import json

from config0_publisher.loggerly import Config0Logger
import boto.ec2

#import random
#import sys
#import logging

#import boto.route53
#import boto.rds2
#import boto.vpc
#import boto.ec2.cloudwatch
#from boto import set_stream_logger
#from boto import set_file_logger

class EC2_connections(object):

    """
    assumes the boto library is installed

    general ec2 connections and attributes for:

    servers
    securitygroups
    ssh keys

    """

    def __init__(self,**kwargs):

        self.classname = 'EC2_connections'
        self.logger = Config0Logger(self.classname)
        self.logger.debug("Instantiating %s" % self.classname)
        self.aws_default_region = os.environ["AWS_DEFAULT_REGION"]
        self.aws_access_key_id = os.environ["AWS_ACCESS_KEY_ID"]
        self.aws_secret_access_key = os.environ["AWS_SECRET_ACCESS_KEY"]

    def _set_conn(self):

        '''simple method to establish a connection to a region'''

        self.conn = boto.ec2.connect_to_region(self.aws_default_region,
                                               aws_access_key_id=self.aws_access_key_id,
                                               aws_secret_access_key=self.aws_secret_access_key)

        return self.conn

    def _regions_list(self):

        '''list the regions for ec2 related actions'''

        regions = boto.ec2.regions()

        return regions
