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
#Written by Gary Leong  <gary@config0.com, May 11,2023

import json
import datetime
import os
import logging
from logging import config

class DateTimeJsonEncoder(json.JSONEncoder):

    def default(self,obj):

        if isinstance(obj,datetime.datetime):
            #newobject = str(obj.timetuple())
            newobject = '-'.join([ str(element) for element in list(obj.timetuple())][0:6])
            return newobject

        return json.JSONEncoder.default(self,obj)

#dup 54534532453245
def nice_json(results):

    try:
        _results = json.dumps(results,sort_keys=True,cls=DateTimeJsonEncoder,indent=4)
    except:
        _results = results

    return _results

class Config0Logger(object):

    def __init__(self,name,**kwargs):

        self.classname = 'Config0Logger'

        logger = get_logger(name,**kwargs)
        self.direct = logger[0]
        self.name = logger[1]
        self.aggregate_msg = None

    def json(self, data=None, msg=None, loglevel="debug"):

        if not data:
            data = {}

        if msg:
            try:
                _msg = "{} \n{}".format(msg, nice_json(data))
            except:
                _msg = "{} \n{}".format(msg, data)
        else:
            try:
                _msg = "\n{}".format(nice_json(data))
            except:
                _msg = "{}".format(data)

        if loglevel == "warn":
            self.direct.warn(_msg)
        elif loglevel == "error":
            self.direct.error(_msg)
        elif loglevel == "critical":
            self.direct.critical(_msg)
        elif loglevel == "info":
            self.direct.info(_msg)
        elif loglevel == "debug":
            self.direct.debug(_msg)
        else:
            self.direct.info(_msg)

    def aggmsg(self,message,new=False,prt=None,cmethod="debug"):

        if not self.aggregate_msg: new = True

        if not new: 
            self.aggregate_msg = "{}\n{}".format(self.aggregate_msg,message)
        else:
            self.aggregate_msg = "\n{}".format(message)

        if not prt: return self.aggregate_msg

        msg = self.aggregate_msg
        self.print_aggmsg(cmethod)

        return msg

    def print_aggmsg(self,cmethod="debug"):

        _method = 'self.{}({})'.format(cmethod,"self.aggregate_msg")
        eval(_method)
        self.aggregate_msg = ""

    def debug_highlight(self,message):
        self.direct.debug("+"*32)
        try:
            self.direct.debug(message)
        except:
            print(message)
        self.direct.debug("+"*32)

    def info(self,message):
        try:
            self.direct.info(message)
        except:
            print(message)

    def debug(self,message):
        try:
            self.direct.debug(message)
        except:
            print(message)

    def critical(self,message):
        self.direct.critical("!"*32)
        try:
            self.direct.critical(message)
        except:
            print(message)
        self.direct.critical("!"*32)

    def error(self,message):
        self.direct.error("*"*32)
        try:
            self.direct.error(message)
        except:
            print(message)
        self.direct.error("*"*32)

    def warning(self,message,highlight=1,symbol="~"):
        return self.warn(message)

    def warn(self,message):
        self.direct.warn("-"*32)
        try:
            self.direct.warn(message)
        except:
            print(message)
        self.direct.warn("-"*32)

def get_logger(name,**kwargs):

    # if stdout_only is set, we won't write to file
    stdout_only = kwargs.get("stdout_only")
    
    # Set loglevel
    loglevel = kwargs.get("loglevel")

    if not loglevel: 
        loglevel = os.environ.get("ED_LOGLEVEL")

    if not loglevel: 
        loglevel = "DEBUG"
    loglevel = loglevel.upper()

    # Set logdir and logfile
    if not stdout_only:

        logdir = kwargs.get("logdir")
        if not logdir: 
            logdir = os.environ.get("LOG_DIR")
        if not logdir: 
            logdir = "/tmp/config0/log"

        logfile = "{}/{}".format(logdir,"ed_main.log")

        if not os.path.exists(logdir): 
            os.system("mkdir -p {}".format(logdir))

        if not os.path.exists(logfile): 
            os.system("touch {}".format(logfile))

    formatter = kwargs.get("formatter","module")

    name_handler = kwargs.get("name_handler",
                              "console,loglevel_file_handler,error_file_handler")

    # defaults for root logger
    logging.basicConfig(level=eval("logging.%s" % loglevel))
    name_handler = [ x.strip() for x in list(name_handler.split(",")) ]

    # Configure loglevel
    # Order of precedence:
    # 1 loglevel specified
    # 2 logcategory specified
    # 3 defaults to "debug"

    log_config = {"version":1}
    log_config["disable_existing_loggers"] = False

    log_config["formatters"] = {
        "simple": {
            "format": "%(asctime)s - %(levelname)s - %(message)s",
            "datefmt": '%Y-%m-%d %H:%M:%S'
        },
        "module": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "datefmt": '%Y-%m-%d %H:%M:%S'
        }
    }

    if stdout_only:

        log_config["handlers"] = {
            "console": {
                "class": "logging.StreamHandler",
                "level": loglevel,
                "formatter": formatter,
                "stream": "ext://sys.stdout"
            }
        }

    else:

        log_config["handlers"] = {
            "console": {
                "class": "logging.StreamHandler",
                "level": loglevel,
                "formatter": formatter,
                "stream": "ext://sys.stdout"
            },
            "info_file_handler": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "INFO",
                "formatter": formatter,
                "filename": logdir+"info.log",
                "maxBytes": 10485760,
                "backupCount": "20",
                "encoding": "utf8"
            },
            "loglevel_file_handler": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": loglevel,
                "formatter": formatter,
                "filename": logdir+loglevel+".log",
                "maxBytes": 10485760,
                "backupCount": "20",
                "encoding": "utf8"
            },
            "error_file_handler": {
                "class": "logging.handlers.RotatingFileHandler",
                "level": "ERROR",
                "formatter": formatter,
                "filename": logdir+"errors.log",
                "maxBytes": 10485760,
                "backupCount": "20",
                "encoding": "utf8"
            }
        }

    log_config["loggers"] = {
        name: {
            "level": loglevel,
            "handlers": name_handler,
            "propagate": False 
        }
    }

    log_config["root"] = {
        "level": loglevel,
        "handlers": name_handler
    }

    config.dictConfig(log_config) 
    logger = logging.getLogger(name)
    logger.setLevel(eval("logging."+loglevel))

    return logger,name
