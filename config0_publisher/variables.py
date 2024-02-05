#!/usr/bin/env python
#
#
#Project: jiffy: A product for building and managing infrastructure: 
#cloud provider services, and servers and their configurations.
#
#Description: A product for building and managing infrastructure. 
#This includes third party API calls for services such as virtual
#cloud servers, load balancers, databases, and other. The product 
#manages connectivity and appropriate communication among these 
#resources.
#
#Copyright (C) Gary Leong - All Rights Reserved
#Unauthorized copying of this file, via any medium is strictly prohibited
#Proprietary and confidential
#Written by Gary Leong  <gwleong@gmail.com, September 17,2022

import os
import json
import traceback

from ast import literal_eval
from config0_publisher.serialization import b64_decode
from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import print_json

def get_init_var_type(value):

    boolean = [ "None",
                "none",
                "null",
                "NONE",
                "None",
                "false",
                "False",
                "FALSE",
                "TRUE",
                "true",
                "True" ]

    if isinstance(value,dict):
        return "dict"
    
    if isinstance(value,list):
        return "list"

    if isinstance(value,float):
        return "float"

    if isinstance(value,bool):
        return "bool"

    if isinstance(value,int):
        return "int"

    try:
        str_value = str(value).strip()
    except:
        return False

    if str_value == "1":
        return "int"

    if str_value == "0":
        return "int"

    if str_value in boolean:
        return "bool"

    return "str"


class EvaluateVar(object):

    def __init__(self):

        self.classname = 'EvaluateVar'

        self.logger = Config0Logger(self.classname)

        # revisit 3542353245
        # the boolean types need to cover
        # boolean for things like Terraform
        # and Ansible
        self.bool_none = [ "None",
                           "none",
                           "null",
                           "NONE",
                           "None",
                           None ]

        self.bool_false = [ "false",
                            "False",
                            "FALSE",
                            False ]

        self.bool_true = [ "TRUE",
                           "true",
                           "True",
                           True ]

    def _set_init_var(self):

        self.results["provided"]["value"] = self.init_value
        self.results["current"]["value"] = self.init_value
        init_type = get_init_var_type(self.init_value)

        if init_type:
            self.results["provided"]["type"] = init_type
            self.results["current"]["type"] = init_type

    def _check_value_is_set(self):

        if not hasattr(self,"init_value"):
            raise Exception("self.init_value not set")

    def is_float(self):

        self._check_value_is_set()

        if isinstance(self.results["check"]["value"],float):
            return True
    
        try:
            if "." not in str(self.results["check"]["value"]):
                raise Exception("is probably an integer")
            updated_value = float(self.results["check"]["value"])
        except:
            return False

        self.results["updated"] = True
        self.results["current"]["value"] = updated_value
        self.results["current"]["type"] = "float"

        return True
    
    def is_integer(self):

        self._check_value_is_set()
    
        if isinstance(self.results["check"]["value"],int):
            return True
    
        if self.results["check"]["value"] in [ "0", 0 ]: 

            self.results["current"]["type"] = "int"
            self.results["current"]["value"] = "0"

            if self.results["check"]["value"] != "0":
                self.results["updated"] = True

            return True

        if self.results["check"]["value"] in [ "1", 1 ]: 

            self.results["current"]["value"] = "1"
            self.results["current"]["type"] = "int"

            if self.results["check"]["value"] != "1":
                self.results["updated"] = True

            return True

        try:
            first_character = self.results["check"]["value"][0]
        except:
            first_character = None

        if first_character in [ "0", 0 ]:
            return False

        try:
            updated_value = int(self.results["check"]["value"])
        except:
            return False

        self.results["current"]["value"] = updated_value
        self.results["current"]["type"] = "int"
        self.results["updated"] = True

        return True


    def check_none(self,value):

        try:
            _value = str(value)
        except:
            return

        if _value in self.bool_none:
            return True

    def check_bool(self,value):

        if str(value) in self.bool_true:
            return "bool",True

        if str(value) in self.bool_false:
            return "bool",False

        if str(value) in self.bool_none:
            return "bool",None

        return None,None

    def is_bool(self):

        self._check_value_is_set()

        if self.results["check"]["value"] in self.bool_true:
            self.results["updated"] = True
            self.results["current"]["value"] = True
            self.results["current"]["type"] = "bool"
            return True

        if self.results["check"]["value"] in self.bool_false:
            self.results["updated"] = True
            self.results["current"]["value"] = False
            self.results["current"]["type"] = "bool"
            return True

        if self.results["check"]["value"] in self.bool_none:
            self.results["updated"] = True
            self.results["current"]["value"] = None
            self.results["current"]["type"] = "bool"
            return True

    def is_str(self):

        self._check_value_is_set()

        if isinstance(self.results["check"]["value"],str):
            self.results["current"]["type"] = "str"
            self.results["current"]["value"] = self.results["check"]["value"]
            return True

        return

    def init_results(self,**kwargs):

        self.results = { "current": {},
                         "check": {},
                         "provided": {}
                         }

        if "value" not in kwargs:
            return

        self.init_value = kwargs["value"]
        self._set_init_var()

        # record default if provided
        if kwargs.get("default"):
            self.results["default"] = kwargs["default"]

        if kwargs.get("default_type"):
            self.results["default_type"] = kwargs["default_type"]

    def _update_objiter(self,**kwargs):

        update_iterobj = kwargs.get("update_iterobj",True)

        if not update_iterobj:
            return self.init_value

        try:
            new_obj = literal_eval(json.dumps(self.init_value))
        except:
            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug(traceback.format_exc())
            self.logger.debug("current init_value {} type {}".format(self.init_value,
                                                                     type(self.init_value)))
            self.logger.json(self.results)
            self.logger.debug("could not update iterable object to not contain unicode")
            new_obj = self.init_value

        return new_obj

    def get(self,**kwargs):

        # update iterobj to have string elements
        # rather than at times contain unicode
        self.init_results(**kwargs)

        # if user specified type in list of "types" in variable
        # types list, we leave them "types" format if possible
        if kwargs.get("user_specified_type"):
            self.results["user_specified_type"] = kwargs["user_specified_type"]
            return self.results["provided"]["type"]

        self._check_value_is_set()

        if isinstance(self.init_value,dict):
            self.results["current"]["value"] = self._update_objiter()
            self.results["current"]["type"] = "dict"
            self.results["initial_check"] = True
            return "dict"

        if isinstance(self.init_value,list):
            self.results["current"]["value"] = self._update_objiter()
            self.results["current"]["type"] = "list"
            self.results["initial_check"] = True
            return "list"

        if isinstance(self.init_value,float):
            self.results["current"]["value"] = self.init_value
            self.results["current"]["type"] = "float"
            self.results["initial_check"] = True
            return "float"

        if isinstance(self.init_value,str):
            self.results["check"]["value"] = self.init_value
        else:
            self.results["check"]["value"] = str(self.init_value)

        init_type = get_init_var_type(self.results["check"]["value"])

        if init_type:
            self.results["check"]["type"] = init_type

        # check value will always be a str
        # or dict/list.  it is needed
        # because True => 1, and False => 0

        if self.is_bool():
            self.results["primary_check"] = True
            return "bool"

        elif self.is_float():
            self.results["primary_check"] = True
            return "float"

        elif self.is_integer():
            self.results["primary_check"] = True
            return "int"

        elif self.is_str():
            self.results["primary_check"] = True
            return "str"

        return "__unknown_variable_type__"

    def set(self,key=None,**kwargs):
        
        self.get(**kwargs)

        if os.environ.get("JIFFY_ENHANCED_LOG") and key:
            self.logger.json(msg='\n\n## key {} ##\n'.format(key),
                             data=self.results)

        return self.results


# ref 532452352341
# dup 532452352341
class SyncClassVarsHelper:

    def __init__(self,**kwargs):

        variables = kwargs.get("variables")
        must_exists = kwargs.get("must_exists")
        non_nullable = kwargs.get("non_nullable")
        inputargs = kwargs.get("inputargs")
        default_values = kwargs.get("default_values")

        self.app_name = kwargs.get("app_name")
        self.app_dir = kwargs.get("app_dir")
        self.os_env_prefix = kwargs.get("os_env_prefix")

        if variables:
            self._variables = variables
        else:
            self._variables = []

        if non_nullable:
            self._non_nullable = non_nullable
        else:
            self._non_nullable = []

        if must_exists:
            self._must_exists = must_exists
        else:
            self._must_exists = []

        if inputargs:
            self._inputargs = inputargs
        else:
            self._inputargs = {}

        if default_values:
            self._default_values = default_values
        else:
            self._default_values = {}

        self.class_vars = {}

        if self.os_env_prefix:
            self.class_vars["os_env_prefix"] = self.os_env_prefix

        if self.app_name:
            self.class_vars["app_name"] = self.app_name

        if self.app_dir:
            self.class_vars["app_dir"] = self.app_dir

    def set_variables(self):

        if not self._variables:
            return

        for _env_var in self._variables:

            if self.os_env_prefix and self.os_env_prefix in _env_var and _env_var in self._inputargs:  # we don't modify os env prefixed vars
                self.class_vars[_env_var] = self._inputargs[_env_var]
            elif _env_var in self._inputargs:
                self.class_vars[_env_var.lower()] = self._inputargs[_env_var]  # we convert to lowercase
            elif _env_var.upper() in os.environ:
                self.class_vars[_env_var.lower()] = os.environ[_env_var.upper()]  # we convert to lowercase
            elif self.os_env_prefix and self.os_env_prefix in _env_var in self._default_values:
                self.class_vars[_env_var] = self._default_values[_env_var]  # we don't modify os env prefixed vars
            elif _env_var in self._default_values:
                self.class_vars[_env_var.lower()] = self._default_values[_env_var]  # we convert to lowercase

    def set_default_values(self):

        if not self._default_values:
            return

        for _k,_v in self._default_values.items():
            if _k.lower() in self.class_vars:
                continue

            self.class_vars[_k.lower()] = _v

    def eval_must_exists(self):

        if not self._must_exists:
            return

        for _k in self._must_exists:

            if _k in self.class_vars:
                continue

            raise Exception(f"class var {_k} must be set")

    def eval_non_nullable(self):

        if not self._non_nullable:
            return

        for _k in self._non_nullable:

            if self.class_vars.get(_k):
                continue

            raise Exception(f"class var {_k} cannot be null/None")

    def set(self,init=None):

        self.set_variables()
        self.set_default_values()

        if not init:
            self.eval_must_exists()
            self.eval_non_nullable()

        return


class EnvVarsToClassVars:

    def __init__(self,**kwargs):

        self.main_env_var_key = kwargs["main_env_var_key"]
        self.app_name = kwargs.get("app_name")
        self.app_dir = kwargs.get("app_dir")
        self.os_env_prefix = kwargs.get("os_env_prefix")

        must_exists = kwargs.get("must_exists")
        non_nullable = kwargs.get("non_nullable")
        default_values = kwargs.get("default_values")

        self.default_keys = kwargs.get("default_keys")

        if non_nullable:
            self._non_nullable = non_nullable
        else:
            self._non_nullable = []

        if must_exists:
            self._must_exists = must_exists
        else:
            self._must_exists = []

        if default_values:
            self._default_values = default_values
        else:
            self._default_values = {}

        self.class_vars = {}

        if self.os_env_prefix:
            self.class_vars["os_env_prefix"] = self.os_env_prefix

        if self.app_name:
            self.class_vars["app_name"] = self.app_name

        if self.app_dir:
            self.class_vars["app_dir"] = self.app_dir

    def init_env_vars(self,**kwargs):

        try:
            self.main_dict = b64_decode(os.environ[self.main_env_var_key])
        except:
            return

        self.env_vars = self.main_dict["env_vars"]
        self.env_vars_to_class_vars(self.env_vars)
    def env_vars_to_class_vars(self,env_vars):

        for key,value in env_vars.items():
            self.class_vars[key.lower()] = value

    def add_env_var(self,_env_var):

        if _env_var.upper() in os.environ:
            #print(f"==> {_env_var} is os.environ")
            self.class_vars[_env_var.lower()] = os.environ[_env_var.upper()]  # we convert to lowercase
        elif self.os_env_prefix and ((self.os_env_prefix in _env_var) and (_env_var in self._default_values)):  # testtest456
            self.class_vars[_env_var] = self._default_values[_env_var]  # we don't modify os env prefixed vars
        elif _env_var in self._default_values:
            #print(f"++> {_env_var} is default_values")
            self.class_vars[_env_var.lower()] = self._default_values[_env_var]  # we convert to lowercase

    def set_default_env_keys(self):

        if not self.default_keys:
            return

        for _env_var in self.default_keys:
            if _env_var.lower() in self.class_vars:
                continue
            self.add_env_var(_env_var)

    def set_default_values(self):

        if not self._default_values:
            return

        for _k,_v in self._default_values.items():
            if _k.lower() in self.class_vars:
                continue
            self.class_vars[_k.lower()] = _v

    def eval_must_exists(self):

        if not self._must_exists:
            return

        for _k in self._must_exists:
            if _k.lower() in self.class_vars:
                continue
            raise Exception(f"class var {_k} must be set")

    def eval_non_nullable(self):

        if not self._non_nullable:
            return

        for _k in self._non_nullable:
            if self.class_vars.get(_k.lower()):
                continue
            raise Exception(f"class var {_k} cannot be null/None")

    def set(self,init=None):

        if init:
            self.init_env_vars()

        self.set_default_env_keys()
        self.set_default_values()
        self.eval_must_exists()
        self.eval_non_nullable()

        return
