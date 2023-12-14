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
#Written by Gary Leong  <gary@config0.com, March 11,2023

import json
import os
from config0_publisher.utilities import print_json
from config0_publisher.loggerly import Config0Logger

class TFConstructor(object):

    def __init__(self,**kwargs):

        self.classname = 'TFConstructor'
        self.logger = Config0Logger(self.classname)
        self.logger.debug("Instantiating %s" % self.classname)

        self.stack = kwargs["stack"]
        self.provider = kwargs["provider"]
        self.execgroup_name = kwargs["execgroup_name"]
        self.resource_name = kwargs["resource_name"]
        self.resource_type = kwargs["resource_type"]
        self.terraform_type = kwargs["terraform_type"]
        self.docker_runtime = kwargs.get("docker_runtime")
        self.include_raw = kwargs.get("include_raw",True)

        self.ssm_format = kwargs.get("ssm_format", ".env")
        self.ssm_obj = kwargs.get("ssm_obj")
        self.ssm_name = kwargs.get("ssm_name")
        self.ssm_prefix = "/config0/statefuls"

        self.output_prefix_key = None
        self.include_keys = []
        self.output_keys = []
        self.exclude_keys = []
        self.maps = {}

        self._init_opt_args()
        
        # if this is not run in an api
        if not os.environ.get("CONFIG0_RESTAPI"):
            self._add_values_to_ssm()

        # for authoring purchasing, we use 
        # tag "db" instead of "resource_values"
        self.resource_values = self.stack.get_tagged_vars(tag="db",
                                                          output="dict")

    def _get_ssm_value(self):

        if self.ssm_format == ".env":
            return self.stack.to_envfile(self.ssm_obj,
                                         b64=True)

        return self.stack.b64_encode(self.ssm_obj)

    def _set_ssm_name(self,value):

        if self.ssm_name:
            return
 
        # stateful_id should be set 100% of the time
        # but adding random just in case it is not set
        if self.stack.stateful_id:
            _name = self.stack.stateful_id
        else:
            _name = self.stack.random_id(size=20).lower()

        if self.stack.get_attr("schedule_id"):
            base_prefix = os.path.join(self.ssm_prefix,
                                       self.stack.schedule_id)
        else:
            base_prefix = "{}".format(self.ssm_prefix)

        if self.ssm_format == ".env":
            self.ssm_name = "{}.env".format(os.path.join(base_prefix,_name))
        else:
            self.ssm_name = os.path.join(base_prefix,_name)

    def _add_values_to_ssm(self):

        if not self.ssm_obj:
            return

        if not self.stack.stateful_id and not self.ssm_name:
            return

        value = self._get_ssm_value()
        self._set_ssm_name(value)

        if self.ssm_prefix in self.ssm_name:
            ssm_key = self.ssm_name.split("{}/".format(self.ssm_prefix))[1]
        else:
            ssm_key = self.ssm_name

        self.stack.add_secret(name=ssm_key,
                              value=value,
                              insert_ssm=True)

    def _init_opt_args(self):

        include = []

        if not hasattr(self.stack,"docker_runtime") or not self.stack.docker_runtime:
            include.append("docker_runtime")
            if self.docker_runtime:
                self.stack.set_variable("docker_runtime",self.docker_runtime,types="str")
            else:
                self.stack.parse.add_required(key="docker_runtime",
                                              default="elasticdev/terraform-run-env:1.3.7",
                                              types="str")

        if not hasattr(self.stack,"stateful_id"):
            include.append("stateful_id")
            self.stack.parse.add_optional(key="stateful_id",
                                          default="_random",
                                          types="str,null")

        if not hasattr(self.stack,"remote_stateful_bucket"):
            include.append("remote_stateful_bucket")
            self.stack.parse.add_optional(key="remote_stateful_bucket",
                                          default="null",
                                          types="str,null")

        if not hasattr(self.stack,"cloud_tags_hash"):
            include.append("cloud_tags_hash")
            self.stack.parse.add_optional(key="cloud_tags_hash",
                                          default="null",
                                          types="str")

        if not hasattr(self.stack,"publish_to_saas"):
            include.append("publish_to_saas")
            self.stack.parse.add_optional(key="publish_to_saas",
                                          default="null",
                                          types="bool,null")

        if not hasattr(self.stack,"timeout"):
            include.append("timeout")
            self.stack.parse.add_optional(key="timeout",
                                          default=1800,
                                          types="int")

        self.stack.parse.tag_key(key="docker_runtime",
                                 tags="resource,db,execgroup_inputargs,runtime_settings")

        self.stack.parse.tag_key(key="remote_stateful_bucket",
                                 tags="resource,db,execgroup_inputargs,runtime_settings")

        self.stack.parse.tag_key(key="cloud_tags_hash",
                                 tags="execgroup_inputargs")

        self.stack.parse.tag_key(key="publish_to_saas",
                                 tags="execgroup_inputargs")

        self.stack.parse.tag_key(key="timeout",
                                 tags="execgroup_inputargs")

        self.stack.reset_variables(include=include)

        if not self.stack.stateful_id:
            self.stack.set_variable("stateful_id",
                                    self.stack.random_id())

        self.stack.parse.tag_key(key="stateful_id",
                                 tags="resource,db,execgroup_inputargs,runtime_settings")

    def _add_to_list(self,existing_keys,keys=None):

        if not keys:
            return

        for _key in keys:

            if _key in existing_keys:
                continue

            existing_keys.append(_key)

    def _add_to_dict(self,existing_values,values=None):

        if not values:
            return

        for _key,_value in values.items():

            if _key in existing_values:
                continue

            existing_values[_key] = _value

    def add_include_keys(self,keys=None):
        return self._add_to_list(self.include_keys,
                                 keys=keys)

    def add_exclude_keys(self,keys=None):
        return self._add_to_list(self.exclude_keys,
                                 keys=keys)

    def add_output_keys(self,keys=None):
        return self._add_to_list(self.output_keys,
                                 keys=keys)

    def add_resource_values(self,values=None):
        return self._add_to_dict(self.resource_values,
                                 values=values)

    def add_query_maps(self,maps=None):
        return self._add_to_dict(self.maps,
                                 values=maps)

    def include(self,keys=None,values=None,maps=None):

        if keys:
            self.add_include_keys(keys)
        elif values:
            self.add_resource_values(values)
        elif maps:
            self.add_query_maps(maps=maps)

    def output(self,keys,prefix_key=None):

        if prefix_key:
            self.output_prefix_key = prefix_key

        self.add_output_keys(keys)

    def exclude(self,keys):

        self.add_exclude_keys(keys)

    def get_resource_params(self):

        resource_params = { "include_raw": self.include_raw }

        if self.include_keys:
            resource_params["include_keys"] = self.include_keys

        if self.exclude_keys:
            resource_params["exclude_keys"] = self.exclude_keys

        if self.maps:
            resource_params["map_keys"] = self.maps

        return resource_params

    def _get_resource_settings(self):

        settings = {}

        env_vars = self.stack.get_tagged_vars(tag="resource",
                                              output="dict",
                                              uppercase=True)

        if self.resource_values:
            settings["resource_values_hash"] = self.stack.b64_encode(self.resource_values)

        if env_vars:
            settings["resource_env_vars_hash"] = self.stack.b64_encode(env_vars)

        if self.output_keys:
            settings["resource_output_keys_hash"] = self.stack.b64_encode(self.output_keys)

        if self.output_prefix_key:
            settings["resource_output_prefix"] = self.output_prefix_key

        return settings

    def _get_runtime_settings(self):

        # docker env vars during execution
        env_vars = self.stack.get_tagged_vars(tag="runtime_settings",
                                              output="dict",
                                              uppercase=True)

        if not env_vars:
            return 

        return {"runtime_env_vars_hash":self.stack.b64_encode(env_vars)}

    def _get_tf_settings(self):

        settings = {}

        # terraform variables converted to TF_VAR_<var>
        tf_vars = self.stack.get_tagged_vars(tag="tfvar",
                                             include_type=True,
                                             output="dict")

        if tf_vars:
            settings["tf_vars_hash"] = self.stack.b64_encode(tf_vars)

        resource_params = self.get_resource_params()

        if resource_params:
            settings["resource_params_hash"] = self.stack.b64_encode(resource_params)

        return settings

    def get_inputargs(self):

        self.stack.verify_variables()

        tf_settings = self._get_tf_settings()
        runtime_settings = self._get_runtime_settings()
        resource_settings = self._get_resource_settings()

        overide_values = self.stack.get_tagged_vars(tag="execgroup_inputargs",
                                                    output="dict")

        execgroup_ref = self.stack.get_locked(execgroup=self.execgroup_name)

        if not execgroup_ref:
            self.stack.logger.warn("execgroup_ref cannot be found through assets locks - will use the latest")
            execgroup_ref = self.execgroup_name

        overide_values["provider"] = self.provider
        overide_values["execgroup_ref"] = execgroup_ref
        overide_values["resource_name"] = self.resource_name
        overide_values["resource_type"] = self.resource_type
        overide_values["terraform_type"] = self.terraform_type

        # user provided overides
        if self.docker_runtime:
            overide_values["docker_runtime"] = self.docker_runtime

        # this is really ssm name
        if self.ssm_name:
            overide_values["ssm_name"] = self.ssm_name

        if self.stack.stateful_id:
            overide_values["stateful_id"] = self.stack.stateful_id

        self._add_to_dict(overide_values,tf_settings)
        self._add_to_dict(overide_values,runtime_settings)
        self._add_to_dict(overide_values,resource_settings)

        inputargs = { "automation_phase": "infrastructure",
                      "human_description": "invoking tf executor",
                      "overide_values":overide_values }

        return inputargs

    def get(self):
        return self.get_inputargs()
