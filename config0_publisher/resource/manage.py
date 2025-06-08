#!/usr/bin/env python
"""
Base class for managing cloud infrastructure resources and command execution.

Provides core functionality for:

Attributes:
    classname (str): Name of the resource command helper class
    cwd (str): Current working directory
    template_dir (str): Directory containing templates
    resources_dir (str): Directory for resource files
    docker_env_file (str): Path to Docker environment file
    inputargs (dict): Input arguments for resource operations
    output (list): Command execution output collection

Environment Variables:
    JIFFY_ENHANCED_LOG: Enable enhanced logging
    DEBUG_STATEFUL: Enable debug mode for stateful operations
    CONFIG0_INITIAL_APPLY: Flag for initial application
"""

import os
from copy import deepcopy

from config0_publisher.loggerly import Config0Logger
from config0_publisher.shellouts import execute4
from config0_publisher.shellouts import execute3
from config0_publisher.serialization import create_envfile
from config0_publisher.serialization import b64_decode
from config0_publisher.serialization import b64_encode
from config0_publisher.shellouts import rm_rf
from config0_publisher.variables import EnvVarsToClassVars

# Import modularized components
from config0_publisher.resource.sync import SyncToShare
from config0_publisher.resource.utils import to_jsonfile, to_json_object
from config0_publisher.resource.env_manager import EnvManager
from config0_publisher.resource.template_manager import TemplateManager
from config0_publisher.resource.logging_helper import LoggingHelper

#############################################
# insert back to 3531543
# lambda456
# testtest456
# tf tweaking
#############################################
from config0_publisher.resource.codebuild import Codebuild
from config0_publisher.resource.lambdabuild import Lambdabuild
from config0_publisher.serialization import b64_decode
from config0_publisher.resource.tf_vars import tf_iter_to_str, get_tf_bool
from config0_publisher.resource.aws_executor import AWSAsyncExecutor
#############################################

class ResourceCmdHelper(SyncToShare):

    def __init__(self, **kwargs):
        """
        stateful_id = abc123
        run_dir -> exec_base_dir - e.g. /tmp/ondisktmp/abc123
        app_dir -> exec_dir - e.g. var/tmp/ansible
        share_dir - share directory with docker or execution container - e.g. /var/tmp/share
        run_share_dir - share directory with stateful_id - e.g. /var/tmp/share/ABC123
        """

        self.classname = 'ResourceCmdHelper'
        self.logger = Config0Logger(self.classname)
        self.logger.debug(f"Instantiating {self.classname}")

        SyncToShare.__init__(self)

        self.cwd = os.getcwd()

        # this can be over written by the inheriting class
        self.template_dir = None
        self.resources_dir = None
        self.docker_env_file = None
        self.inputargs = {}
        self.output = []

        self.shelloutconfig = kwargs.get("shelloutconfig")
        self.os_env_prefix = kwargs.get("os_env_prefix")
        self.app_name = kwargs.get("app_name")
        self.app_dir = kwargs.get("app_dir")

        if not hasattr(self, "build_env_vars"):
            self.build_env_vars = kwargs.get("build_env_vars")

        if not self.build_env_vars:
            self.build_env_vars = {}

        # Initialize helper components
        self.env_manager = EnvManager(
            os_env_prefix=self.os_env_prefix,
            app_name=self.app_name,
            app_dir=self.app_dir
        )
        
        # The template manager will be initialized later when exec_dir is set

        self.logging_helper = LoggingHelper(
            logger=self.logger,
            stateful_id=kwargs.get("stateful_id")
        )

        ResourcePhases.__init__(self)

        # set specified env variables
        self.env_manager.set_env_vars(env_vars=kwargs.get("env_vars"), clobber=True)
        self.env_manager.set_os_env_prefix()
        self._set_app_params()

        self._init_syncvars(**kwargs)
        self._finalize_set_vars()

        self._set_build_timeout()
        self._set_aws_region()

        # ref 34532453245
        self.final_output = None

        # Initialize template manager now that exec_dir is set
        self.template_manager = TemplateManager(
            logger=self.logger,
            os_env_prefix=self.os_env_prefix,
            app_name=self.app_name,
            exec_dir=self.exec_dir,
            template_dir=self.template_dir
        )

    # Keep core methods and Terraform-specific methods here
    # [The rest of the TF-specific code as shown in your snippet would go here]

    #############################################
    # insert back to 3531543
    # lambda456
    # testtest456
    # tf tweaking
    #############################################

    def _set_runtime_env_vars(self, method="create"):
        """Sets runtime environment variables needed for Terraform execution"""

        # Build environment variables only needed when initially creating
        if method != "create":
            return

        try:
            exclude_vars = list(self.tf_configs["tf_vars"].keys())
        except (KeyError, AttributeError) as e:
            exclude_vars = self.exclude_tfvars

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
            "tf_runtime": self.tf_runtime
        }

        # Usually associated with create
        if method in ["apply", "create", "pre-create"]:
            if self.build_env_vars:
                cinputargs["build_env_vars"] = self.build_env_vars
            if self.ssm_name:
                cinputargs["ssm_name"] = self.ssm_name
        # Usually associated with destroy/validate/check
        elif os.environ.get("CONFIG0_BUILD_ENV_VARS"):
            cinputargs["build_env_vars"] = b64_decode(os.environ["CONFIG0_BUILD_ENV_VARS"])

        return cinputargs

    def _set_build_method(self):
        """Determines whether to use CodeBuild or Lambda for execution"""

        if os.environ.get("USE_CODEBUILD"):  # longer than 900 seconds
            self.build_method = "codebuild"
        elif os.environ.get("USE_LAMBDA"):  # shorter than 900 seconds
            self.build_method = "lambda"
        elif self.method in ["validate", "check", "pre-create"]:
            self.build_method = "lambda"
        elif os.environ.get("USE_AWS", True):  # select codebuild or lambda
            if int(self.build_timeout) > 800:
                self.build_method = "codebuild"
            else:
                self.build_method = "lambda"
        else:  # the default
            self.build_method = "lambda"

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

    def _setup_and_exec_in_aws(self, method, create_remote_state=None):
        """Sets up and executes Terraform in AWS"""

        self._set_runtime_env_vars(method=method)

        # Use backend to track state file
        if create_remote_state:
            self.create_aws_tf_backend()
        return self._exec_in_aws(method=method)

    def create(self):
        """Creates Terraform resources"""

        if not self.stateful_id:
            self.logger.error("STATEFUL_ID needs to be set")

        # If we render template files, we don't create tfvars file
        if not self.template_manager.templify(app_template_vars="TF_EXEC_TEMPLATE_VARS", **self.inputargs):
            self.exclude_tfvars = self._create_terraform_tfvars()

        if not os.path.exists(self.exec_dir):
            raise Exception(f"terraform directory must exist at {self.exec_dir} when creating tf")

        self._set_runtime_env_vars(method="create")
        self.create_aws_tf_backend()

        # Submit and run required env file
        self.create_build_envfile()

        if self.build_method == "codebuild":
            self.build_method = "lambda"  # we run pre-create in lambda first
            _use_codebuild = True
        else:
            _use_codebuild = None

        pre_creation = self._exec_in_aws(method="pre-create")
        if not pre_creation.get("status"):
            self.logger.error("pre-create failed")
            return pre_creation

        if _use_codebuild:
            self.build_method = "codebuild"

        tf_results = self._exec_in_aws(method="create")

        # Should never get this far if execution failed
        # because eval_failure should exit out
        if not tf_results.get("status"):
            return tf_results

        self.post_create()
        return tf_results

    def run(self):
        """Main execution method"""

        self._set_build_method()

        if self.method == "create":
            tf_results = self.create()
        elif self.method == "destroy":
            tf_results = self._setup_and_exec_in_aws("destroy")
        elif self.method == "validate":
            tf_results = self._setup_and_exec_in_aws("validate")
        elif self.method == "check":
            tf_results = self._setup_and_exec_in_aws("check")
        #else:
        #    usage()
        #    print(f'Method "{self.method}" not supported!')
        #    exit(4)

        # Evaluation of log should be at the end
        # outside of _exec_in_aws
        self.eval_log(tf_results, local_log=True)

    #############################################

    def _exec_in_aws(self, method="create"):
        """Executes Terraform command in AWS"""

        cinputargs = self._get_aws_exec_cinputargs(method=method)
        
        # Create AWS Async Executor with current settings
        executor = AWSAsyncExecutor(
            resource_type="terraform", 
            resource_id=self.stateful_id,
            tmp_bucket=self.tmp_bucket,
            stateful_id=self.stateful_id,
            method=method,
            aws_region=self.aws_region,
            app_dir=self.app_dir,
            app_name=self.app_name,
            remote_stateful_bucket=getattr(self, 'remote_stateful_bucket', None),
            build_timeout=self.build_timeout
        )
        
        # Use the appropriate execution method based on build_method
        if self.build_method == "lambda":
            results = executor.exec_lambda(**cinputargs)
        elif self.build_method == "codebuild":
            results = executor.exec_codebuild(**cinputargs)
        else:
            return False

        if method == "destroy":
            try:
                os.chdir(self.cwd)
            except (FileNotFoundError, PermissionError) as e:
                os.chdir("/tmp")

        self.eval_failure(results, method)
        return results
