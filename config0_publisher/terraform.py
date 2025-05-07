#!/usr/bin/env python

import json
import os
from config0_publisher.shellouts import execute3
from config0_publisher.loggerly import Config0Logger


def get_tfstate_file_remote(remote_stateful_bucket, stateful_id):
    """Fetch and parse a Terraform state file from S3."""
    cmd = (f'aws s3 cp s3://{remote_stateful_bucket}/{stateful_id}/state/'
           f'{stateful_id}.tfstate /tmp/{stateful_id}.tfstate')

    try:
        execute3(cmd, output_to_json=False, exit_error=True)
        tfstate_file = f"/tmp/{stateful_id}.tfstate"
        
        with open(tfstate_file) as json_file:
            data = json.load(json_file)
        
        os.system(f'rm -rf {tfstate_file}')
        return data
    except Exception as e:
        raise Exception(f"Failed to get remote tfstate file: {str(e)}")


class TFConstructor:
    """Terraform constructor that manages terraform execution configurations."""
    
    def __init__(self, **kwargs):
        """Initialize the TFConstructor with required parameters."""
        self.classname = 'TFConstructor'
        self.logger = Config0Logger(self.classname)
        self.logger.debug(f'Instantiating {self.classname}')

        # Required parameters
        self.stack = kwargs["stack"]
        self.provider = kwargs["provider"]
        self.execgroup_name = kwargs["execgroup_name"]
        self.resource_name = kwargs["resource_name"]
        self.resource_type = kwargs["resource_type"]
        self.resource_id = kwargs.get('resource_id')

        # Optional parameters
        self.tf_runtime = kwargs.get("tf_runtime")
        self.terraform_type = kwargs.get("terraform_type")
        self.docker_image = kwargs.get("docker_image")

        # SSM related parameters
        self.ssm_format = kwargs.get("ssm_format", ".env")
        self.ssm_obj = kwargs.get("ssm_obj")
        self.ssm_name = kwargs.get("ssm_name")
        self.ssm_prefix = "/config0-iac/saas/users"

        # Output configuration
        self.output_prefix_key = None
        self.include_keys = []
        self.output_keys = []
        self.exclude_keys = []
        self.maps = {}

        # Initialize optional arguments
        self._init_opt_args()

        # Add values to SSM if not running in an API context
        if not os.environ.get("CONFIG0_RESTAPI"):
            self._add_values_to_ssm()

        # Get tagged resource values
        self.resource_values = self.stack.get_tagged_vars(tag="db", output="dict")

    def _get_ssm_value(self, ssm_format):
        """Format SSM values based on format type."""
        if ssm_format == ".env":
            return self.stack.to_envfile(self.ssm_obj,
                                         b64=True,
                                         include_export=True)
        return self.stack.b64_encode(self.ssm_obj)

    def _set_ssm_name(self):
        """Set SSM name if not already defined."""
        if self.ssm_name:
            return

        # Generate name from stateful_id or random ID
        if self.stack.stateful_id:
            _name = self.stack.stateful_id
        else:
            _name = self.stack.random_id(size=20).lower()

        # Set base prefix
        if self.stack.get_attr("schedule_id"):
            base_prefix = os.path.join(self.ssm_prefix,
                                       self.stack.schedule_id)
        else:
            base_prefix = f"{self.ssm_prefix}"

        # Generate full path based on format
        if self.ssm_format == ".env":
            self.ssm_name = f"{os.path.join(base_prefix, _name)}.env"
        else:
            self.ssm_name = os.path.join(base_prefix, _name)

    def _add_values_to_ssm(self):
        """Add configuration values to SSM parameter store."""
        # Get Infracost API key if available
        infracost_api_key = None
        if self.stack.inputvars.get("infracost_api_key_hash"):
            try:
                infracost_api_key = self.stack.b64_decode(
                    self.stack.inputvars["infracost_api_key_hash"]
                )
            except Exception as e:
                self.logger.error(f"Failed to decode infracost_api_key_hash: {str(e)}")
        elif self.stack.inputvars.get("infracost_api_key"):
            infracost_api_key = self.stack.inputvars["infracost_api_key"]

        # Update SSM object with Infracost API key
        if not self.ssm_obj and infracost_api_key:
            self.ssm_obj = {"INFRACOST_API_KEY": infracost_api_key}
        elif self.ssm_obj and infracost_api_key:
            self.ssm_obj["INFRACOST_API_KEY"] = infracost_api_key

        # Exit if we don't have necessary values
        if (not self.stack.stateful_id and not self.ssm_name) or not self.ssm_obj:
            return

        # Get formatted value and set SSM name
        try:
            value = self._get_ssm_value(self.ssm_format)
            self._set_ssm_name()

            # Extract key from full path
            if self.ssm_prefix in self.ssm_name:
                ssm_key = self.ssm_name.split(f"{self.ssm_prefix}/")[1]
            else:
                ssm_key = self.ssm_name

            # Add secret to stack
            self.stack.add_secret(name=ssm_key,
                                value=value,
                                insert_ssm=True)
        except Exception as e:
            self.logger.error(f"Failed to add values to SSM: {str(e)}")

    def _init_opt_args(self):
        """Initialize optional arguments for the stack."""
        include = []

        # Handle docker image and TF runtime
        if not hasattr(self.stack, "tf_runtime") or not self.stack.tf_runtime:
            include.append("docker_image")
            if self.docker_image:
                self.stack.set_variable("docker_image",
                                        self.docker_image,
                                        types="str")
            else:
                self.stack.parse.add_required(key="docker_image",
                                            default="tofu:1.9.1",
                                            types="str")
        else:
            self.stack.set_variable("docker_image",
                                    self.tf_runtime,
                                    types="str")

        # Add stateful_id if not present
        if not hasattr(self.stack, "stateful_id"):
            include.append("stateful_id")
            self.stack.parse.add_optional(key="stateful_id",
                                        default="_random",
                                        types="str,null")

        # Add remote_stateful_bucket if not present
        if not hasattr(self.stack, "remote_stateful_bucket"):
            include.append("remote_stateful_bucket")
            self.stack.parse.add_optional(key="remote_stateful_bucket",
                                        default="null",
                                        types="str,null")

        # Add cloud_tags_hash if not present
        if not hasattr(self.stack, "cloud_tags_hash"):
            include.append("cloud_tags_hash")
            self.stack.parse.add_optional(key="cloud_tags_hash",
                                        default="null",
                                        types="str")

        # Add publish_to_saas if not present
        if not hasattr(self.stack, "publish_to_saas"):
            include.append("publish_to_saas")
            self.stack.parse.add_optional(key="publish_to_saas",
                                        default="null",
                                        types="bool,null")

        # Add timeout if not present
        if not hasattr(self.stack, "timeout"):
            include.append("timeout")
            self.stack.parse.add_optional(key="timeout",
                                        default=600,
                                        types="int")

        # Add create_remote_state if not present
        if not hasattr(self.stack, "create_remote_state"):
            include.append("create_remote_state")
            self.stack.parse.add_optional(key="create_remote_state",
                                        default=True,
                                        types="bool,str")

        # Add drift_protection if not present
        if not hasattr(self.stack, "drift_protection"):
            include.append("drift_protection")
            self.stack.parse.add_optional(key="drift_protection",
                                        default=True,
                                        types="bool,str")

        # Tag keys with appropriate tags
        self.stack.parse.tag_key(key="docker_image",
                               tags="resource,db,execgroup_inputargs,tf_exec_env")

        self.stack.parse.tag_key(key="remote_stateful_bucket",
                               tags="resource,db,execgroup_inputargs,tf_exec_env")

        self.stack.parse.tag_key(key="create_remote_state",
                               tags="execgroup_inputargs")

        self.stack.parse.tag_key(key="drift_protection",
                               tags="execgroup_inputargs")

        self.stack.parse.tag_key(key="cloud_tags_hash",
                               tags="execgroup_inputargs")

        self.stack.parse.tag_key(key="publish_to_saas",
                               tags="execgroup_inputargs")

        self.stack.parse.tag_key(key="timeout",
                               tags="execgroup_inputargs")

        # Reset variables and set stateful_id if needed
        self.stack.reset_variables(include=include)

        if not self.stack.stateful_id:
            self.stack.set_variable("stateful_id",
                                  self.stack.random_id())

        self.stack.parse.tag_key(key="stateful_id",
                               tags="resource,db,execgroup_inputargs,tf_exec_env")

    @staticmethod
    def _add_to_list(existing_keys, keys=None):
        """Add new keys to an existing list, avoiding duplicates."""
        if not keys:
            return

        for _key in keys:
            if _key in existing_keys:
                continue

            existing_keys.append(_key)

    @staticmethod
    def _add_to_dict(existing_values, values=None):
        """Add new key-value pairs to an existing dict, avoiding duplicates."""
        if not values:
            return

        for _key, _value in values.items():
            if _key in existing_values:
                continue

            existing_values[_key] = _value

    def add_include_keys(self, keys=None):
        """Add keys to the include_keys list."""
        return self._add_to_list(self.include_keys, keys=keys)

    def add_exclude_keys(self, keys=None):
        """Add keys to the exclude_keys list."""
        return self._add_to_list(self.exclude_keys, keys=keys)

    def add_output_keys(self, keys=None):
        """Add keys to the output_keys list."""
        return self._add_to_list(self.output_keys, keys=keys)

    def add_resource_values(self, values=None):
        """Add values to the resource_values dictionary."""
        return self._add_to_dict(self.resource_values, values=values)

    def add_query_maps(self, maps=None):
        """Add maps to the maps dictionary."""
        return self._add_to_dict(self.maps, values=maps)

    def include(self, keys=None, values=None, maps=None):
        """Include keys, values or maps based on provided parameters."""
        if keys:
            self.add_include_keys(keys)
        elif values:
            self.add_resource_values(values)
        elif maps:
            self.add_query_maps(maps=maps)

    def output(self, keys, prefix_key=None):
        """Configure output keys and optional prefix key."""
        if prefix_key:
            self.output_prefix_key = prefix_key

        self.add_output_keys(keys)

    def exclude(self, keys):
        """Configure keys to exclude."""
        self.add_exclude_keys(keys)

    def _get_resource_configs_hash(self):
        """Generate resource configuration hash for terraform execution."""
        try:
            env_vars = self.stack.get_tagged_vars(
                tag="resource",
                output="dict",
                uppercase=True
            )

            env_vars["METHOD"] = "create"

            _configs = {
                "include_keys": self.include_keys,
                "exclude_keys": self.exclude_keys,
                "maps": self.maps,
                "values": self.resource_values,
                "env_vars": env_vars,
                "output_keys": self.output_keys,
                "output_prefix_key": self.output_prefix_key
            }

            return self.stack.b64_encode(_configs)
        except Exception as e:
            self.logger.error(f"Failed to generate resource configs hash: {str(e)}")
            raise

    def _get_runtime_env_vars(self):
        """Get environment variables for terraform runtime execution."""
        try:
            env_vars = self.stack.get_tagged_vars(tag="tf_exec_env",
                                                output="dict",
                                                uppercase=True)
            if not env_vars:
                return None

            return self.stack.b64_encode(env_vars)
        except Exception as e:
            self.logger.error(f"Failed to get runtime env vars: {str(e)}")
            return None

    def _get_tf_vars_hash(self):
        """Get terraform variables encoded as a hash."""
        try:
            tf_vars = self.stack.get_tagged_vars(tag="tfvar",
                                                include_type=True,
                                                output="dict")
            return self.stack.b64_encode(tf_vars)
        except Exception as e:
            self.logger.error(f"Failed to get tf vars hash: {str(e)}")
            raise

    def get_inputargs(self):
        """Generate input arguments for the terraform execution."""
        try:
            self.stack.verify_variables()

            execgroup_ref = self.stack.get_locked_asset(execgroup=self.execgroup_name)

            if not execgroup_ref:
                self.stack.logger.warn("execgroup_ref cannot be found through assets locks - will use the latest")
                execgroup_ref = self.execgroup_name

            overide_values = self.stack.get_tagged_vars(tag="execgroup_inputargs",
                                                      output="dict")

            # Set required values
            overide_values["provider"] = self.provider
            overide_values["execgroup_ref"] = execgroup_ref
            overide_values["resource_name"] = self.resource_name
            overide_values["resource_type"] = self.resource_type

            # Set optional values if available
            if self.resource_id:
                overide_values["resource_id"] = self.resource_id

            if self.terraform_type:
                overide_values["terraform_type"] = self.terraform_type

            # Get configuration hashes
            overide_values["tf_vars_hash"] = self._get_tf_vars_hash()
            overide_values["resource_configs_hash"] = self._get_resource_configs_hash()
            
            runtime_env_vars = self._get_runtime_env_vars()
            if runtime_env_vars:
                overide_values["runtime_env_vars_hash"] = runtime_env_vars

            # Add docker image if specified
            if self.docker_image:
                overide_values["docker_image"] = self.docker_image

            # Add SSM name if specified
            if self.ssm_name:
                overide_values["ssm_name"] = self.ssm_name

            # Add stateful_id if available
            if self.stack.stateful_id:
                overide_values["stateful_id"] = self.stack.stateful_id

            return {
                "automation_phase": "infrastructure",
                "human_description": "invoking tf executor",
                "overide_values": overide_values,
            }
        except Exception as e:
            self.logger.error(f"Error in get_inputargs: {str(e)}")
            raise

    def get(self):
        """Return input arguments for terraform execution."""
        return self.get_inputargs()