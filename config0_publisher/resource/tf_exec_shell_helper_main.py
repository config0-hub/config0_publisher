#!/usr/bin/env python
"""
Terraform Execution Helper Main for Config0

This module provides the main helper class for Terraform operations, executing them through
AWS Lambda or CodeBuild. It handles configuration management, environment variable setup,
state file management, and command execution for Terraform operations like create,
destroy, validate, and check.

The module uses Config0's resource management system to handle inputs, manage state,
and coordinate execution across AWS services.
"""

# Copyright 2025 Gary Leong gary@config0.com
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
from config0_publisher.utilities import to_json
from config0_publisher.resource.aws_executor import AWSAsyncExecutor
from config0_publisher.loggerly import Config0Logger
from config0_publisher.serialization import b64_decode
from config0_publisher.resource.codebuild import Codebuild
from config0_publisher.resource.lambdabuild import Lambdabuild
from config0_publisher.resource.manage import ResourceCmdHelper
from config0_publisher.resource.tf_configure import ConfigureTFConfig0Db
from config0_publisher.resource.tf_vars import tf_iter_to_str, get_tf_bool
from config0_publisher.resource.config0_settings_env_vars import Config0SettingsEnvVarHelper


class TFExecShellHelperMain(ResourceCmdHelper, Config0SettingsEnvVarHelper, ConfigureTFConfig0Db):

    def __init__(self):

        self.classname = 'TFExecShellHelperMain'

        self.logger = Config0Logger(
            self.classname,
            logcategory="cloudprovider"
        )

        # TODO: we force async_mode True
        self.async_mode = True

        self.logger.debug(f"Instantiating {self.classname}")
        self.method = os.environ.get("METHOD", "create")

        ConfigureTFConfig0Db.__init__(self)

        # Main input settings from environment var CONFIG0_RESOURCE_EXEC_SETTINGS_HASH
        Config0SettingsEnvVarHelper.__init__(self)
        self.eval_config0_resource_settings(self.method)

        set_must_exists = [
            "tmp_bucket",
            "log_bucket"
        ]

        set_default_values = {
            "failed_destroy": None,
            "tf_runtime_env_vars": None,
            "ssm_name": None
        }

        if self.method == "create":
            set_must_exists.extend([
                "ssm_name",
                "stateful_id", 
                "remote_stateful_bucket"
            ])

        ResourceCmdHelper.__init__(
            self,
            main_env_var_key="TF_RUNTIME_SETTINGS",
            app_name="terraform",
            set_must_exists=set_must_exists,
            set_default_values=set_default_values
        )

        self._apply_tf_runtime_env_vars()

        self.terraform_tfvars = os.path.join(
            self.exec_dir,
            "terraform.tfvars"
        )

        # Initialize build_method - child classes should override set_build_method() if needed
        self.build_method = None

    def _apply_tf_runtime_env_vars(self):
        """Applies Terraform runtime environment variables"""

        if hasattr(self, "tf_runtime_env_vars") and self.tf_runtime_env_vars:
            for _k, _v in self.tf_runtime_env_vars.items():
                self.runtime_env_vars[_k.upper()] = _v

    def _ensure_build_method(self):
        """
        Ensures build_method is set before execution.
        
        Sets a default build_method if not already set by child class.
        Child classes should override set_build_method() to customize the logic.
        """
        if hasattr(self, "build_method") and self.build_method:
            return

        # Default logic: use lambda for fast operations, codebuild for long ones
        if self.method in ["validate", "check"]:
            self.build_method = "lambda"
        elif hasattr(self, "build_timeout") and self.build_timeout:
            if int(self.build_timeout) > 800:
                self.build_method = "codebuild"
            else:
                self.build_method = "lambda"
        else:
            # Default to lambda
            self.build_method = "lambda"

        self.logger.debug(f"build_method set to: {self.build_method} (default)")

    def set_runtime_env_vars(self, method="create"):
        """Sets runtime environment variables needed for Terraform execution"""

        # Build environment variables only needed when initially creating
        if method != "create":
            return

        exclude_vars = list(self.tf_configs["tf_vars"].keys())

        # Insert TF_VAR_* os vars
        self.insert_os_env_prefix_envs(self.build_env_vars, exclude_vars)

        # Set environment variables for Terraform execution
        self.build_env_vars["BUILD_TIMEOUT"] = self.build_timeout

        if self.docker_image:
            self.build_env_vars["DOCKER_IMAGE"] = self.docker_image

        if self.runtime_env_vars:
            self.build_env_vars.update(self.runtime_env_vars)

        self.build_env_vars["TF_RUNTIME"] = self.tf_runtime
        self.build_env_vars["SHARE_DIR"] = self.share_dir
        self.build_env_vars["RUN_SHARE_DIR"] = self.run_share_dir
        self.build_env_vars["LOG_BUCKET"] = self.log_bucket

        if hasattr(self, "tmp_bucket") and self.tmp_bucket:
            self.build_env_vars["OUTPUT_BUCKET"] = self.tmp_bucket
            self.build_env_vars["TMP_BUCKET"] = self.tmp_bucket

        self.build_env_vars["STATEFUL_ID"] = self.stateful_id
        self.build_env_vars["APP_DIR"] = self.app_dir
        self.build_env_vars["APP_NAME"] = self.app_name
        self.build_env_vars["REMOTE_STATEFUL_BUCKET"] = self.remote_stateful_bucket
        self.build_env_vars["TMPDIR"] = "/tmp"

        # SSM name setting
        if self.build_env_vars.get("SSM_NAME"):  # usually set in create
            self.ssm_name = self.build_env_vars["SSM_NAME"]
        elif os.environ.get("SSM_NAME"):
            self.ssm_name = os.environ["SSM_NAME"]
            self.build_env_vars["SSM_NAME"] = self.ssm_name

    def _create_terraform_tfvars(self):
        """Creates terraform.tfvars file from TF_VAR_* variables"""

        if self.tf_configs and self.tf_configs.get("tf_vars"):
            _tfvars = self.tf_configs["tf_vars"]
        else:
            _tfvars = self.get_os_env_prefix_envs()

        if not _tfvars:
            return

        with open(self.terraform_tfvars, "w") as f:
            for _key, _input in _tfvars.items():
                _type = _input["type"]
                _value = _input["value"]
                _quoted = True

                if _type in ["dict", "list"]:
                    _value = tf_iter_to_str(_value)
                    _quoted = None
                elif _type == "bool":
                    _value = get_tf_bool(_value)
                    _quoted = None
                elif _type in ["float", "int"]:
                    _quoted = None

                self.logger.debug(f"_create_terraform_tfvars (new_format): {_key} -> <{_type}> {_value}")

                _entry = f'{_key} \t= "{_value}"' if _quoted else f'{_key} \t= {_value}'
                f.write(f"{_entry}\n")

        self.logger.debug("*" * 32)
        self.logger.debug(f"\nWrote terraform.tfvars: {self.terraform_tfvars}\n")
        self.logger.debug("*" * 32)

        return _tfvars.keys()

    def _get_aws_exec_cinputargs(self, method="create"):
        """Gets AWS execution input arguments"""

        cinputargs = {
            "method": method,
            "build_timeout": self.build_timeout,
            "run_share_dir": self.run_share_dir,
            "app_dir": self.app_dir,
            "remote_stateful_bucket": self.remote_stateful_bucket,
            "aws_region": self.aws_region,
            "version": self.version,
            "binary": self.binary,
            "tf_runtime": self.tf_runtime,
            "execution_id": self.execution_id,
            "execution_id_path": self.execution_id_path
        }

        # Usually associated with create
        if method in ["apply", "create"]:
            if self.build_env_vars:
                cinputargs["build_env_vars"] = self.build_env_vars
            if self.ssm_name:
                cinputargs["ssm_name"] = self.ssm_name
        # Usually associated with destroy/validate/check
        elif os.environ.get("CONFIG0_BUILD_ENV_VARS"):
            cinputargs["build_env_vars"] = b64_decode(os.environ["CONFIG0_BUILD_ENV_VARS"])

        # on initial apply we will destroy infra if create fails
        if os.environ.get("CONFIG0_INITIAL_APPLY"):
            cinputargs["initial_apply"] = True

        return cinputargs
            
    def _exec_in_aws(self, method="create"):
        """Executes Terraform command in AWS with execution tracking"""

        # Ensure build_method is set before execution
        self._ensure_build_method()

        # Validate build_method is set
        if not hasattr(self, "build_method") or not self.build_method:
            raise Exception("build_method must be set before execution. Override set_build_method() in child class or ensure _ensure_build_method() is called.")

        if self.build_method not in ["lambda", "codebuild"]:
            raise Exception(f"build_method must be 'lambda' or 'codebuild', got: {self.build_method}")

        # Always set execution_id for tracking
        self._set_execution_id()

        # Get execution input arguments
        cinputargs = self._get_aws_exec_cinputargs(method=method)

        # Create AWS Async Executor with current settings
        executor = AWSAsyncExecutor(
            resource_type="terraform",
            resource_id=self.stateful_id,
            execution_id=self.execution_id,
            output_bucket=self.tmp_bucket,
            stateful_id=self.stateful_id,
            method=method,
            aws_region=self.aws_region,
            app_dir=self.app_dir,
            app_name=self.app_name,
            remote_stateful_bucket=getattr(self, 'remote_stateful_bucket', None),
            build_timeout=self.build_timeout
        )

        # Use the appropriate build method and prepare invocation configuration
        if self.build_method == "lambda":
            _awsbuild = Lambdabuild(**cinputargs)
            invocation_config = _awsbuild.pre_trigger()

            # Use the unified execute method with sync parameter
            results = executor.execute(
                execution_type="lambda",
                async_mode=self.async_mode,
                **invocation_config
            )

        elif self.build_method == "codebuild":
            _awsbuild = Codebuild(**cinputargs)
            inputargs = _awsbuild.pre_trigger()

            # Use the unified execute method with sync parameter
            results = executor.execute(
                execution_type="codebuild",
                async_mode=self.async_mode,
                **inputargs
            )

            if not self.async_mode:
                results = _awsbuild.retrieve(build_id=results["build_id"])
            else:
                if results.get("done"):
                    results = _awsbuild.retrieve(build_id=results["status"]["build_id"])
                    results["done"] = True
                    results["async_mode"] = True
        else:
            raise Exception("build_method needs be either lambda/codebuild")

        if method == "destroy":
            try:
                os.chdir(self.cwd)
            except (FileNotFoundError, PermissionError) as e:
                os.chdir("/tmp")

        if self.async_mode:
            if results.get("done"):
                if "results" in results:
                    results = results["results"]
            elif results.get("in_progress"):
                return {"cinputargs": cinputargs,
                        "results": results}

        if not isinstance(results, dict):
            results = to_json(results)

        if results.get("status") in ["error", False, "False", "false"]:
            results["status"] = False
        elif "return_code" in results and int(results.get("return_code")) != 0:
            results["status"] = False
            results["exitcode"] = int(results["return_code"])

        if "tf_status" in results:
            if results.get("tf_status") in ["False", False]:
                results["status"] = False
            else:
                results["status"] = results["tf_status"]

        if "tf_exitcode" in results:
            try:
                results["exitcode"] = int(results["tf_exitcode"])
            except:
                results["exitcode"] = results["tf_exitcode"]

        self.eval_log(results)
        self.eval_failure(results, method)

        return {
            "cinputargs": cinputargs,
            "results": results
        }

    def create_aws_tf_backend(self):
        """Creates AWS Terraform backend configuration"""

        _file = os.path.join(
            self.run_share_dir,
            self.app_dir,
            "backend.tf"
        )

        contents = f"""terraform {{
  backend "s3" {{
    bucket = "{self.remote_stateful_bucket}"
    key    = "{self.stateful_id}/state/{self.stateful_id}.tfstate"
    region = "{self.aws_backend_region}"
  }}
}}
"""
        with open(_file, "w") as file:
            file.write(contents)

    def setup_and_exec_in_aws(self, method):
        """Sets up and executes Terraform in AWS"""

        self.set_runtime_env_vars(method=method)

        # Use backend to track state file
        self.create_aws_tf_backend()

        return self._exec_in_aws(method=method)["results"]

    def create(self):
        """Creates Terraform resources"""

        if not self.stateful_id:
            self.logger.error("STATEFUL_ID needs to be set")

        # If we render template files, we don't create tfvars file
        if not self.templify(app_template_vars="TF_EXEC_TEMPLATE_VARS", **self.inputargs):
            self.exclude_tfvars = self._create_terraform_tfvars()

        if not os.path.exists(self.exec_dir):
            raise Exception(f"terraform directory must exist at {self.exec_dir} when creating tf")

        self.set_runtime_env_vars(method="create")
        self.create_aws_tf_backend()

        # Submit and run required env file
        self.create_build_envfile()

        tf_results = self._exec_in_aws(method="create")["results"]

        if tf_results.get("done"):
            self.delete_phases_to_json_file()

        if tf_results.get("phases") and not tf_results.get("done"):
            self.write_phases_to_json_file(tf_results)
            return tf_results

        if tf_results.get("status") or tf_results.get("tf_status"):
            if hasattr(self, "post_create") and callable(self.post_create):
                self.post_create()

        return tf_results


