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

import string
import random
import datetime
import json
import os
import hashlib

from config0_publisher.loggerly import Config0Logger
from config0_publisher.shellouts import mkdir
from config0_publisher.shellouts import rm_rf

class DateTimeJsonEncoder(json.JSONEncoder):

    def default(self,obj):

        if isinstance(obj,datetime.datetime):
            #newobject = str(obj.timetuple())
            newobject = '-'.join([ str(element) for element in list(obj.timetuple())][0:6])
            return newobject

        return json.JSONEncoder.default(self,obj)

def print_json(results):
    print(json.dumps(results,sort_keys=True,cls=DateTimeJsonEncoder,indent=4))

def nice_json(results):
    return json.dumps(results,sort_keys=True,cls=DateTimeJsonEncoder,indent=4)

def convert_str2list(_object,split_char=None,exit_error=None):

    if split_char:
        entries = [ entry.strip() for entry in _object.split(split_char) ]
    else:
        entries = [ entry.strip() for entry in _object.split(" ") ]

    return entries

def convert_str2json(_object,exit_error=None):

    if isinstance(_object,dict):
        return _object

    if isinstance(_object,list):
        return _object

    logger = Config0Logger("convert_str2json")

    try:
        _object = json.loads(_object)
        status = True
        #logger.debug("Success: Converting str to a json")
    except:
        #logger.debug("Cannot convert str to a json.  Will try to eval")
        status = False

    if not status:
        try:
            _object = eval(_object)
            #logger.debug("Success: Evaluating str to a json")
        except:
            status = False
            #logger.debug("Cannot eval str to a json.")
            if exit_error:
                exit(13)

            return False

    return _object

def to_list(_object,split_char=None,exit_error=None):

    return convert_str2list(_object,
                            split_char=split_char,
                            exit_error=exit_error)

def to_json(_object,exit_error=None):

    return convert_str2json(_object,
                            exit_error=exit_error)

def shellout_hash(string):

    try:
        cmd = os.popen('echo "%s" | md5sum | cut -d " " -f 1' % string, "r")
        ret = cmd.read().rstrip()
    except: 
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            print("Failed to calculate the md5sum of a string %s" % string)
        return False

    return ret

def get_hash(data):

    '''determines the hash of a data object'''

    logger = Config0Logger("get_hash")

    try:
        calculated_hash = hashlib.md5(data).hexdigest()
    except:
        logger.debug("Falling back to shellout md5sum for hash")
        calculated_hash = shellout_hash(data)

    if not calculated_hash:
        logger.error("Could not calculate hash for %s" % data)
        return False

    return calculated_hash

# dup 4523452346
def id_generator(size=6,chars=string.ascii_uppercase+string.digits):

    '''generates id randomly'''

    return ''.join(random.choice(chars) for x in range(size))

def get_dict_frm_file(file_path):

    '''
    looks at the file_path in the format
    key=value

    and parses it and returns a dictionary
    '''

    sparams = {}

    rfile = open(file_path,"r")

    non_blank_lines = (line.strip() for line in rfile.readlines() if line.strip())

    for bline in non_blank_lines:
        key,value = bline.split("=")
        sparams[key] = value

    return sparams

class OnDiskTmpDir(object):

    def __init__(self,**kwargs):

        self.tmpdir = kwargs.get("tmpdir")

        if not self.tmpdir:
            self.tmpdir = "/tmp"

        self.subdir = kwargs.get("subdir","ondisktmp")

        if self.subdir:
            self.basedir = "{}/{}".format(self.tmpdir,
                                          self.subdir)
        else:
            self.basedir = self.tmpdir

        self.classname = "OnDiskTmpDir"

        mkdir("/tmp/ondisktmpdir/log")

        self.logger = Config0Logger(self.classname)

        if kwargs.get("init",True):
            self.set_dir(**kwargs)

    def set_dir(self,**kwargs):

        createdir = kwargs.get("createdir",True)

        self.fqn_dir,self.dir = generate_random_path(self.basedir,
                                                     folder_depth=1,
                                                     folder_length=16,
                                                     createdir=createdir,
                                                     string_only=True)

        return self.fqn_dir

    def get(self,**kwargs):

        if not self.fqn_dir:
            msg = "fqn_dir has not be set"
            raise Exception(msg)

        self.logger.debug('Returning fqn_dir "{}"'.format(self.fqn_dir))

        return self.fqn_dir

    def delete(self,**kwargs):

        self.logger.debug('Deleting fqn_dir "{}"'.format(self.fqn_dir))

        return rm_rf(self.fqn_dir)

def generate_random_path(basedir,folder_depth=1,folder_length=16,createdir=False,string_only=None):

    '''
    returns random folder path with specified parameters
    '''

    cwd = basedir

    for _ in range(folder_depth):

        if string_only:
            random_dir = id_generator(folder_length,
                                      chars=string.ascii_lowercase)
        else:
            random_dir = id_generator(folder_length)

        cwd = cwd+"/"+random_dir

    if createdir:
        mkdir(cwd)

    return cwd,random_dir

# dup 34523532452t33t
def get_values_frm_json(json_file=None):

    if not json_file:
        return

    if not os.path.exists(json_file):
        print("WARN: json {} does not exists".format(json_file))
        return

    try:
        with open(json_file) as json_file:
            values = json.load(json_file)
        print("retrieved values from {}".format(json_file))
    except:
        values = None
        print("ERROR: could not retrieved from json file {}".format(json_file))

    return values