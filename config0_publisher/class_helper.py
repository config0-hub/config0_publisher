#!/usr/bin/env python

import logging
import re
import os
#import boto3
#import gzip
#from io import BytesIO
#from time import sleep
#from time import time
#from config0_publisher.loggerly import Config0Logger

class SetClassVarsHelper:

    def __init__(self,set_env_vars=None,kwargs=None,env_vars=None,default_values=None,set_default_null=None):

        if set_env_vars:
            self.set_env_vars = set_env_vars
        else:
            self.set_env_vars = None

        self.kwargs = kwargs
        self.env_vars = env_vars
        self.default_values = default_values

        if not self.kwargs:
            self.kwargs = {}

        if not self.env_vars:
            self.env_vars = {}

        if not self.default_values:
            self.default_values = {}

        self.set_default_null = set_default_null

        # track the class vars set with this
        self._vars_set = {}

    def _set_class_default_vars(self):

        if not self.default_values:
            return

        for key,value in self.default_values.items():

            if key in self._vars_set:
                continue

            # testtest456
            print("5"*32)
            print("5"*32)
            print(f"key={key} value={value}")
            print("5"*32)
            print("5"*32)
            self._vars_set[key] = value

    def set_class_vars_srcs(self):

        if not self.set_env_vars:
            return

        env_vars_keys = list(self.set_env_vars.keys())
        print(env_vars_keys)
        print(env_vars_keys)
        print(env_vars_keys)
        print(type(env_vars_keys))
        print(type(env_vars_keys))
        print(len(env_vars_keys))
        print(len(env_vars_keys))
        raise

        if self.default_values:
            env_vars_keys.extend(self.default_values.keys())

        for env_var_key in env_vars_keys:

            if env_var_key in self.kwargs:
                self._vars_set[env_var_key] = self.kwargs[env_var_key]
                _expression = f'self.{env_var_key}="{self.kwargs[env_var_key]}"'
            elif env_var_key.upper() in self.env_vars:
                self._vars_set[env_var_key] = self.env_vars[env_var_key.upper()]
                _expression = f'self.{env_var_key}="{self.env_vars[env_var_key.upper()]}"'
            elif env_var_key.upper() in os.environ:
                self._vars_set[env_var_key] = os.environ[env_var_key.upper()]
                _expression = f'self.{env_var_key}="{os.environ[env_var_key.upper()]}"'
            elif env_var_key.lower() in self.default_values:
                self._vars_set[env_var_key.lower()] = self.default_values[env_var_key.lower()]
                _expression = f'self.{env_var_key.lower()}="{self.default_values[env_var_key.lower()]}"'
            else:
                _expression = None

            if _expression:
                # testtest456
                print("0"*32)
                print("0"*32)
                print(f"_expression {_expression}")
                print("0"*32)
                print("0"*32)
                exec(_expression)
                continue

            print("1"*32)
            print(f"env_var {env_var_key}")
            print("2"*32)
            print(f"_expression {_expression}")
            print("3"*32)

            if self.set_env_vars.get(env_var_key):  # must_exists
                raise Exception("variable {} needs to be set".format(env_var_key))

            if self.set_default_null:
                self._vars_set[env_var_key] = None
                print("set None for variable {}".format(env_var_key))
                exec('self.{}=None'.format(env_var_key))

        #self._set_class_default_vars()