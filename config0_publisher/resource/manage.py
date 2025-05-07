#!/usr/bin/env python
"""
Base class for managing cloud infrastructure resources and command execution.

Provides core functionality for:
- Command execution and output processing
- Template rendering
- Resource file handling
- Environment variable management
- Docker integration
- Stateful operations

Attributes:
    classname (str): Name of the resource command helper class
    cwd (str): Current working directory
    template_dir (str): Directory containing templates
    resources_dir (str): Directory for resource files
    docker_env_file (str): Path to Docker environment file
    inputargs (dict): Input arguments for resource operations
    output (list): Command execution output collection

    # TODO phases not fully implemented
    # phases allow for non-blocking/bg execution
    # => submit, retrieve
    phases_info (dict): Information about all phases
    phase (str): Current execution phase
    current_phase (dict): Details of current phase

Environment Variables:
    JIFFY_ENHANCED_LOG: Enable enhanced logging
    DEBUG_STATEFUL: Enable debug mode for stateful operations
    CONFIG0_INITIAL_APPLY: Flag for initial application
"""

import base64
import os
import jinja2
import glob
import json
import shutil
import stat
import subprocess
from pathlib import Path
from time import sleep
from copy import deepcopy

from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import print_json
from config0_publisher.utilities import to_json
from config0_publisher.utilities import get_values_frm_json
from config0_publisher.utilities import get_hash
from config0_publisher.utilities import eval_str_to_join
from config0_publisher.shellouts import execute4
from config0_publisher.shellouts import execute3
from config0_publisher.serialization import create_envfile
from config0_publisher.serialization import b64_decode
from config0_publisher.serialization import b64_encode
from config0_publisher.templating import list_template_files
from config0_publisher.output import convert_config0_output_to_values
from config0_publisher.shellouts import rm_rf
from config0_publisher.variables import EnvVarsToClassVars


def to_jsonfile(values, filename, exec_dir=None):
    """
    Write values to a JSON file in the config0_resources directory.
    """
    if not exec_dir:
        exec_dir = os.getcwd()

    file_dir = os.path.join(exec_dir, "config0_resources")
    file_path = os.path.join(file_dir, filename)

    # Create directory if it doesn't exist
    Path(file_dir).mkdir(parents=True, exist_ok=True)

    try:
        with open(file_path, "w") as file:
            file.write(json.dumps(values))
        status = True
        print(f"Successfully wrote contents to {file_path}")
    except Exception as e:
        print(f"Failed to write contents to {file_path}: {str(e)}")
        status = False

    return status


def _to_json(output):
    """Convert output to JSON if it's not already a dictionary."""
    if isinstance(output, dict):
        return output

    try:
        _output = to_json(output)
        if not _output:
            raise Exception("output is None")
        if not isinstance(_output, dict):
            raise Exception("output is not a dict")
        output = _output
    except Exception:
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            print("Could not convert output to json")

    return output


class ResourceCmdHelper:
    """Base helper class for resource command operations."""

    def __init__(self, **kwargs):
        """
        Initialize the ResourceCmdHelper instance.
        
        Args:
            **kwargs: Configuration options including:
                stateful_id: Unique identifier for stateful operations
                run_dir/exec_base_dir: Base execution directory
                app_dir/exec_dir: Application directory
                share_dir: Directory to share with containers
                run_share_dir: Shared directory with stateful ID
        """
        self.classname = 'ResourceCmdHelper'
        self.logger = Config0Logger(self.classname)
        self.logger.debug(f"Instantiating {self.classname}")

        self.cwd = os.getcwd()

        # These can be overwritten by inheriting classes
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

        self.phases_params_hash = kwargs.get("phases_params_hash")
        self.phases_params = kwargs.get("phases_params")

        self.phases_info = None
        self.phase = None  # can be "run" since will only have one phase
        self.current_phase = None

        self._set_phases_params()

        # Set specified environment variables
        self._set_env_vars(env_vars=kwargs.get("env_vars"),
                          clobber=True)

        self._set_os_env_prefix()
        self._set_app_params()

        self._init_syncvars(**kwargs)
        self._finalize_set_vars()

        self._set_build_timeout()
        self._set_aws_region()

        self.final_output = None

    def _set_build_timeout(self):
        """Set build timeout from environment variables or default."""
        if hasattr(self, "build_timeout") and self.build_timeout:
            return

        try:
            self.build_timeout = int(os.environ.get("BUILD_TIMEOUT"))
        except (TypeError, ValueError):
            self.build_timeout = None

        if self.build_timeout:
            return

        try:
            self.build_timeout = int(os.environ.get("TIMEOUT")) - 90
        except (TypeError, ValueError):
            self.build_timeout = None

        if self.build_timeout:
            return

        self.build_timeout = 500

    def _set_aws_region(self):
        """Set AWS region from environment variables or default."""
        self.aws_backend_region = os.environ.get("AWS_BACKEND_REGION") or "us-east-1"

        if hasattr(self, "aws_region") and self.aws_region:
            return

        self.aws_region = os.environ.get("AWS_DEFAULT_REGION")

        if self.aws_region:
            return

        self.aws_region = "us-east-1"

    def _set_phases_params(self):
        """Set phase parameters from provided values or environment."""
        if self.phases_params_hash:
            return

        if self.phases_params:
            self.phases_params_hash = b64_encode(self.phases_params)
            return

        if os.environ.get("PHASES_PARAMS_HASH"):
            self.phases_params_hash = os.environ.get("PHASES_PARAMS_HASH")
            return

    def init_phase_run(self):
        """Initialize phase execution with possible delay."""
        if not self.current_phase:
            return

        try:
            timewait = int(self.current_phase["timewait"])
        except (KeyError, TypeError, ValueError):
            timewait = None

        if not timewait:
            return

        sleep(timewait)

    def get_phase_inputargs(self):
        """Get input arguments for the current phase."""
        if not self.current_phase:
            return None

        try:
            inputargs = self.current_phase["inputargs"]
        except KeyError:
            inputargs = {}

        return inputargs

    def _finalize_set_vars(self):
        """Finalize variable setup and synchronization."""
        self._set_stateful_params()
        self._set_exec_dir()
        self._set_docker_settings()
        self._set_mod_env_vars()
        self._get_docker_env_filepath()

        self._set_special_keywords_classvars()

        # Execute final time to synchronize class vars
        self.set_class_vars()

        # Ensure vars are synchronized
        self.syncvars.set()

        # Sync to environment variables
        self._set_env_vars(env_vars=self.syncvars.class_vars)
        self._set_json_files()

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            try:
                self._print_out_key_class_vars()
            except Exception:
                self.logger.debug("could not print out debug class vars")

    def _set_json_files(self):
        """Set paths for resource and phases JSON files."""
        if not hasattr(self, "config0_resource_json_file") or not self.config0_resource_json_file:
            self.config0_resource_json_file = os.environ.get("CONFIG0_RESOURCE_JSON_FILE")

        if not hasattr(self, "config0_phases_json_file") or not self.config0_phases_json_file:
            self.config0_phases_json_file = os.environ.get("CONFIG0_PHASES_JSON_FILE")

        if not self.config0_resource_json_file:
            try:
                self.config0_resource_json_file = os.path.join(self.stateful_dir,
                                                              f"resource-{self.stateful_id}.json")
            except Exception:
                self.config0_resource_json_file = None

        self.logger.debug(f'u4324: CONFIG0_RESOURCE_JSON_FILE "{self.config0_resource_json_file}"')

        if not self.config0_phases_json_file:
            try:
                self.config0_phases_json_file = os.path.join(self.stateful_dir,
                                                            f"phases-{self.stateful_id}.json")
            except Exception:
                self.config0_phases_json_file = None

        self.logger.debug(f'u4324: CONFIG0_PHASES_JSON_FILE "{self.config0_phases_json_file}"')

    def _debug_print_out_key_class_vars(self):
        """Debug output of class variables."""
        for _k, _v in self.syncvars.class_vars.items():
            try:
                self.logger.debug(f"{_k} -> {_v}")
            except Exception:
                self.logger.warn(f"could not print class vars {_k}")

    def _set_special_keywords_classvars(self):
        """Set special keyword class variables with appropriate values."""
        run_share_dir = self.syncvars.class_vars.get("run_share_dir")

        keys = [
            "chrootfiles_dest_dir",
            "working_dir"
        ]

        for key in keys:
            if not self.syncvars.class_vars.get(key):
                continue

            value = self.syncvars.class_vars[key]

            if value not in ["_set_to_run_share_dir", "_set_to_share_dir"]:
                continue

            if not run_share_dir:
                self.logger.warn(f"could not set {key} run_share_dir")
                self.syncvars.class_vars[key] = None
                setattr(self, key, None)
            else:
                self.syncvars.class_vars[key] = run_share_dir
                setattr(self, key, run_share_dir)

    def _init_syncvars(self, **kwargs):
        """Initialize synchronization variables for class and environment."""
        set_must_exists = kwargs.get("set_must_exists")
        set_non_nullable = kwargs.get("set_non_nullable")
        set_default_values = kwargs.get("set_default_values")
        main_env_var_key = kwargs.get("main_env_var_key")

        must_exists = ["stateful_id"]
        non_nullable = []

        default_keys = [
            "stateful_id",
            "chrootfiles_dest_dir",
            "working_dir",
            "stateful_dir",
            "exec_base_dir",
            "tmp_bucket",
            "log_bucket",
            "run_share_dir",
            "remote_stateful_bucket",
            "tmpdir",
            "method",
            "share_dir",
            "docker_image",
            "mod_execgroup",
            "destroy_env_vars",
            "validate_env_vars",
            "schedule_id",
            "run_id",
            "job_instance_id",
            "config0_resource_json_file",
            "config0_phases_json_file"
        ]

        default_values = {
            "share_dir": "/var/tmp/share",
            "run_share_dir": None,
            "tmp_bucket": None,
            "log_bucket": None,
            "stateful_id": None,
            "destroy_env_vars": None,
            "validate_env_vars": None,
            "mod_execgroup": None,
            "docker_image": None,
            "tmpdir": "/tmp",
            "exec_base_dir": os.getcwd()
        }

        if set_must_exists:
            must_exists.extend(set_must_exists)

        if set_non_nullable:
            non_nullable.extend(set_non_nullable)

        if set_default_values:
            default_values.update(set_default_values)

        self.syncvars = EnvVarsToClassVars(
            main_env_var_key=main_env_var_key,
            os_env_prefix=self.os_env_prefix,
            app_name=self.app_name,
            app_dir=self.app_dir,
            must_exists=must_exists,
            non_nullable=non_nullable,
            default_keys=default_keys,
            default_values=default_values)

        self.syncvars.set(init=True)
        self.set_class_vars()

    def set_class_vars(self, class_vars=None):
        """Set class variables from provided dictionary."""
        if not class_vars:
            class_vars = self.syncvars.class_vars

        for _k, _v in class_vars.items():
            # Skip if the class var already exists and is not None/False
            if hasattr(self, _k) and getattr(self, _k):
                continue

            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug(f" ## variable set: {_k} -> {_v}")

            setattr(self, _k, _v)

    def _set_env_vars(self, env_vars=None, clobber=False):
        """Set environment variables from dictionary."""
        auto_clobber_keys = [
            "CHROOTFILES_DEST_DIR",
            "WORKING_DIR"
        ]

        set_env_vars = env_vars

        if not set_env_vars:
            return

        for _k, _v in set_env_vars.items():
            if self.os_env_prefix and self.os_env_prefix in _k:
                _key = _k
            else:
                _key = _k.upper()

            if _v is None:
                if os.environ.get("JIFFY_ENHANCED_LOG"):
                    print(f"{_key} -> None - skipping")
                continue

            if _key in os.environ and _key in auto_clobber_keys:
                if os.environ.get("JIFFY_ENHANCED_LOG"):
                    print(f"{_key} -> {_v} already set/will clobber")
            elif _key in os.environ and not clobber:
                if os.environ.get("JIFFY_ENHANCED_LOG"):
                    print(f"{_key} -> {_v} already set as {os.environ[_key]}")
                continue

            if os.environ.get("JIFFY_ENHANCED_LOG"):
                print(f"{_key} -> {_v}")

            os.environ[_key] = str(_v)

    def _set_os_env_prefix(self):
        """Set OS environment prefix based on app name."""
        if self.os_env_prefix:
            return

        if self.app_name == "terraform":
            self.os_env_prefix = "TF_VAR"
        elif self.app_name == "ansible":
            self.os_env_prefix = "ANS_VAR"

    def _get_template_vars(self, **kwargs):
        """Get template variables from environment."""
        # If app_template_vars is provided, use it
        _template_vars = kwargs.get("app_template_vars")

        if not _template_vars and self.app_name:
            _template_vars = f"{self.app_name}_EXEC_TEMPLATE_VARS"

        if not os.environ.get(_template_vars.upper()):
            _template_vars = "ED_EXEC_TEMPLATE_VARS"

        if os.environ.get(_template_vars.upper()):
            return [_var.strip() for _var in os.environ.get(_template_vars.upper()).split(",")]

        if not self.os_env_prefix:
            return None

        # Get template_vars e.g. "ANS_VAR_<var>"
        _template_vars = []

        for _var in os.environ.keys():
            if self.os_env_prefix not in _var:
                continue

            self.logger.debug(f"{self.os_env_prefix} found in {_var}")
            self.logger.debug(f"templating variable {_var}")
            _template_vars.append(_var)

        if not _template_vars:
            self.logger.warn("ED_EXEC_TEMPLATE_VARS and <APP> template vars not set/given")

        return _template_vars

    def _set_mod_env_vars(self):
        """Set modified environment variables."""
        try:
            self.destroy_env_vars = eval(self.destroy_env_vars)
        except Exception:
            self.destroy_env_vars = None

        self.syncvars.class_vars["destroy_env_vars"] = self.destroy_env_vars

        try:
            self.validate_env_vars = eval(self.validate_env_vars)
        except Exception:
            self.validate_env_vars = None

        self.syncvars.class_vars["validate_env_vars"] = self.validate_env_vars

    def _set_docker_settings(self):
        """Set Docker image settings."""
        # Docker image explicitly set
        if self.docker_image:
            return

        # Set default by app_name
        if not self.app_name:
            return

        # Terraform typically does not use docker runtime
        if self.app_name == "terraform":
            return

        # Docker image not set but app_name is set
        self.docker_image = f"config0/{self.app_name}-run-env"
        self.syncvars.class_vars["docker_image"] = self.docker_image

    def _mkdir(self, dir_path):
        """Create directory if it doesn't exist."""
        if os.path.exists(dir_path):
            return

        Path(dir_path).mkdir(parents=True, exist_ok=True)

    def _set_stateful_params(self):
        """Set stateful operation parameters."""
        self.postscript_path = None
        self.postscript = None

        if not self.stateful_id:
            return

        if not self.run_share_dir:
            self.run_share_dir = os.path.join(self.share_dir,
                                             self.stateful_id)

            self.syncvars.class_vars["run_share_dir"] = self.run_share_dir

        self._mkdir(self.run_share_dir)

    def _set_app_params(self):
        """Set application parameters."""
        if not self.app_name:
            return

        # Set app_dir
        if not self.app_dir:
            self.app_dir = os.environ.get(f"{self.app_name.upper()}_DIR")

        if not self.app_dir:
            self.app_dir = f"var/tmp/{self.app_name}"

        if self.app_dir[0] == "/":
            self.app_dir = self.app_dir[1:]

        # This can be overridden by inheriting class
        if not self.shelloutconfig:
            self.shelloutconfig = f"config0-publish:::{self.app_name}::resource_wrapper"

    def _set_exec_dir(self):
        """Set execution directory."""
        if self.stateful_id:
            self.exec_dir = self.run_share_dir
        else:
            self.exec_dir = self.exec_base_dir

        # Override the exec_dir from _set_stateful_params
        if self.app_dir:
            self.exec_dir = os.path.join(self.exec_dir,
                                        self.app_dir)

        self.syncvars.class_vars["exec_dir"] = self.exec_dir

        self._mkdir(self.exec_dir)

        if hasattr(self, "exec_dir") and self.exec_dir:
            self.template_dir = f"{self.exec_dir}/_config0_templates"
            self.resources_dir = os.path.join(self.exec_dir, "config0_resources")

    def _get_resource_files(self):
        """Get resource files from resources directory."""
        self.logger.debug(f"getting json files from resources_dir {self.resources_dir}")

        if not os.path.exists(self.resources_dir):
            self.logger.debug(f"DOES NOT EXIST resources_dir {self.resources_dir}")
            return None

        _files = glob.glob(f"{self.resources_dir}/*.json")

        self.logger.debug(_files)

        if not _files:
            return None
        
        resources = []

        for _file in _files:
            try:
                with open(_file, "r") as f:
                    _values = json.loads(f.read())
                resources.append(_values)
            except Exception:
                self.logger.warn(f"could not retrieve resource json contents from {_file}")

        if not resources:
            return None

        if len(resources) == 1:
            return resources[0]

        return resources

    def get_os_env_prefix_envs(self, remove_os_environ=True):
        """
        Get OS environment prefix variables and return them as lowercase without prefix.
        """
        if not self.os_env_prefix:
            return {}

        _split_key = f"{self.os_env_prefix}_"
        inputargs = {}

        for i in list(os.environ.keys()):
            if self.os_env_prefix not in i:
                continue

            _var = i.split(_split_key)[1].lower()
            inputargs[_var] = os.environ[i]

            if remove_os_environ:
                del os.environ[i]

        return inputargs

    def get_app_env_keys(self):
        """Get application environment keys."""
        if not self.os_env_prefix:
            return {}

        try:
            _env_keys = [_key for _key in os.environ.keys() if self.os_env_prefix in _key]
        except Exception:
            _env_keys = None

        self.logger.debug_highlight(f'app_env_keys "{_env_keys}" for os_env_prefix "{self.os_env_prefix}"')

        return _env_keys

    def insert_os_env_prefix_envs(self, env_vars, exclude_vars=None):
        """Insert OS environment prefix variables into env_vars."""
        _env_keys = self.get_app_env_keys()

        if not _env_keys:
            return

        if not exclude_vars:
            exclude_vars = []

        _split_key = f"{self.os_env_prefix}_"

        for _env_key in _env_keys:
            _var = _env_key.split(_split_key)[1].lower()

            if _var in exclude_vars:
                self.logger.debug(f"insert_os_env_prefix_envs - excluding {_env_key}")
                continue

            _env_value = os.environ.get(_env_key)

            if not _env_value:
                continue

            if _env_value in ["False", "false", "null", False]:
                _env_value = "false"

            if _env_value in ["True", "true", True]:
                _env_value = "true"

            env_vars[_env_key] = _env_value

    def append_log(self, log):
        """Append log content to log file."""
        append = True

        if os.environ.get("JIFFY_LOG_FILE"):
            logfile = os.environ["JIFFY_LOG_FILE"]
        elif os.environ.get("CONFIG0_LOG_FILE"):
            logfile = os.environ["CONFIG0_LOG_FILE"]
        elif os.environ.get("LOG_FILE"):
            logfile = os.environ["LOG_FILE"]
        else:
            logfile = f"/tmp/{self.stateful_id}.log"
            append = False

        if isinstance(log, list) or eval_str_to_join(log):
            try:
                _str = "\n".join(log)
            except Exception:
                _str = None
        else:
            _str = None

        if _str:
            output = _str
        else:
            output = log

        mode = "a" if append else "w"
        with open(logfile, mode) as file:
            file.write("#"*32)
            file.write("\n# append log\n")
            file.write("#"*32)
            file.write("\n")
            file.write(output)
            file.write("\n")
            file.write("#"*32)
            file.write("\n")

        return logfile

    @staticmethod
    def to_resource_db(resources):
        """Convert resources to JSON and print to output."""
        output = _to_json(resources)
        print('_config0_begin_output')
        print(output)
        print('_config0_end_output')

    def _get_docker_env_filepath(self):
        """Get Docker environment file path."""
        _docker_env_file = self.get_env_var("DOCKER_ENV_FILE",
                                           default=".env")

        if not self.run_share_dir:
            return None

        try:
            self.docker_env_file = os.path.join(self.run_share_dir,
                                               _docker_env_file)
        except Exception:
            self.docker_env_file = None

        self.syncvars.class_vars["docker_env_file"] = self.docker_env_file

        return self.docker_env_file

    def get_env_var(self, variable, default=None, must_exists=None):
        """Get environment variable with various prefixes."""
        _value = os.environ.get(variable)

        if _value:
            return _value

        if self.os_env_prefix:
            _value = os.environ.get(f"{self.os_env_prefix}_{variable}")

            if _value:
                return _value

            _value = os.environ.get(f"{self.os_env_prefix}_{variable.lower()}")

            if _value:
                return _value

            _value = os.environ.get(f"{self.os_env_prefix}_{variable.upper()}")

            if _value:
                return _value

        if default is not None:
            return default

        if must_exists:
            raise Exception(f"{variable} does not exist")

        return None

    @staticmethod
    def print_json(values):
        """Print values as JSON."""
        print_json(values)

    def templify(self, **kwargs):
        """Apply templates using environment variables."""
        clobber = kwargs.get("clobber")
        _template_vars = self._get_template_vars(**kwargs)

        if not _template_vars:
            self.logger.debug_highlight("template vars is not set or empty")
            return None

        self.logger.debug_highlight(f"template vars {_template_vars} not set or empty")

        if not self.template_dir:
            self.logger.warn("template_dir not set (None) - skipping templating")
            return None

        template_files = list_template_files(self.template_dir)

        if not template_files:
            self.logger.warn(f"template_files in directory {self.template_dir} empty - skipping templating")
            return None

        for _file_stats in template_files:
            template_filepath = _file_stats["file"]

            file_dir = os.path.join(self.exec_dir,
                                   _file_stats["directory"])

            file_path = os.path.join(self.exec_dir,
                                    _file_stats["directory"],
                                    _file_stats["filename"].split(".ja2")[0])

            Path(file_dir).mkdir(parents=True, exist_ok=True)

            if os.path.exists(file_path) and not clobber:
                self.logger.warn(f"destination templated file already exists at {file_path} - skipping templifying of it")
                continue

            self.logger.debug(f"creating templated file file {file_path} from {template_filepath}")

            template_vars = {}

            if self.os_env_prefix:
                self.logger.debug(f"using os_env_prefix {self.os_env_prefix}")
                _split_char = f"{self.os_env_prefix}_"
            else:
                _split_char = None

            if not _template_vars:
                self.logger.error("_template_vars is empty")
                exit(9)

            self.logger.debug(f"_template_vars {_template_vars}")

            for _var in _template_vars:
                _value = None
                _mapped_key = None

                if self.os_env_prefix:
                    if self.os_env_prefix in _var:
                        _key = _var.split(_split_char)[1]
                        _value = os.environ.get(_var)
                    else:
                        _key = str(f"{self.os_env_prefix}_{_var}")
                        _value = os.environ.get(_key)

                    if _value:
                        _mapped_key = _key

                if not _value:
                    _value = os.environ.get(str(_var))
                    if _value:
                        _mapped_key = _var

                if not _value:
                    _value = os.environ.get(str(_var.upper()))
                    if _value:
                        _mapped_key = _var.upper()

                self.logger.debug("")
                self.logger.debug(f"mapped_key {_mapped_key}")
                self.logger.debug(f"var {_var}")
                self.logger.debug(f"value {_value}")
                self.logger.debug("")

                if not _value:
                    self.logger.warn(f"skipping templify var {_var}")
                    continue

                value = _value.replace("'", '"')

                # Include both uppercase and regular keys
                template_vars[_mapped_key] = value
                template_vars[_mapped_key.upper()] = value

            self.logger.debug("")
            self.logger.debug(f"template_vars {template_vars}")
            self.logger.debug("")

            try:
                template_loader = jinja2.FileSystemLoader(searchpath="/")
                template_env = jinja2.Environment(loader=template_loader)
                template = template_env.get_template(template_filepath)
                output_text = template.render(template_vars)
                with open(file_path, "w") as writefile:
                    writefile.write(output_text)
            except Exception as e:
                self.logger.error(f"Error templating {template_filepath}: {str(e)}")
                continue

        return True

    def write_key_to_file(self, **kwargs):
        """
        Write the value of a key in kwargs to a file.
        """
        key = kwargs["key"]
        filepath = kwargs["filepath"]
        split_char = kwargs.get("split_char")
        add_return = kwargs.get("add_return", True)
        copy_to_share = kwargs.get("copy_to_share")
        deserialize = kwargs.get("deserialize")

        try:
            permission = int(kwargs.get("permission"))
        except (TypeError, ValueError):
            permission = 0o400  # Default permission for SSH private keys

        if not self.inputargs.get(key):
            return None

        _value = self.inputargs[key]

        if deserialize:
            _value = b64_decode(_value)

        if split_char is None:
            _lines = _value
        elif split_char == "return":
            _lines = _value.split('\\n')
        else:
            _lines = _value

        try:
            with open(filepath, "w") as wfile:
                for _line in _lines:
                    wfile.write(_line)
                    if add_return:
                        wfile.write("\n")

            if permission:
                os.chmod(filepath, permission)

            if copy_to_share:
                self.copy_file_to_share(filepath)

            return filepath
        except Exception as e:
            self.logger.error(f"Error writing key to file {filepath}: {str(e)}")
            return None

    def copy_file_to_share(self, srcfile, dst_subdir=None):
        """Copy a file to the share directory."""
        if not self.run_share_dir:
            self.logger.debug("run_share_dir not defined - skipping sync-ing ...")
            return None
            
        try:
            # Create destination directory if needed
            _dirname = os.path.dirname(self.run_share_dir)
            Path(_dirname).mkdir(parents=True, exist_ok=True)

            _file_subpath = os.path.basename(srcfile)

            if dst_subdir:
                _file_subpath = f"{dst_subdir}/{_file_subpath}"
                # Create dst_subdir if needed
                dst_path = os.path.join(self.run_share_dir, dst_subdir)
                Path(dst_path).mkdir(parents=True, exist_ok=True)

            dstfile = f"{self.run_share_dir}/{_file_subpath}"

            # Copy file
            shutil.copy2(srcfile, dstfile)
            return dstfile
        except Exception as e:
            self.logger.error(f"Error copying file to share: {str(e)}")
            return None

    def sync_to_share(self, exclude_existing=None):
        """Synchronize files to share directory."""
        if not self.run_share_dir:
            self.logger.debug("run_share_dir not defined - skipping sync-ing ...")
            return None

        try:
            # Create destination directory if needed
            _dirname = os.path.dirname(self.run_share_dir)
            Path(_dirname).mkdir(parents=True, exist_ok=True)

            # Copy directory contents
            source_dir = Path(self.exec_dir)
            target_dir = Path(self.run_share_dir)

            for item in source_dir.glob('**/*'):
                if item.is_file():
                    # Get the relative path
                    relative_path = item.relative_to(source_dir)
                    destination = target_dir / relative_path

                    # Create parent directories if they don't exist
                    destination.parent.mkdir(parents=True, exist_ok=True)

                    # Skip existing files if exclude_existing is True
                    if exclude_existing and destination.exists():
                        continue

                    # Copy with metadata (timestamps, permissions)
                    shutil.copy2(item, destination)

            self.logger.debug(f"Sync-ed to run share dir {self.run_share_dir}")
            return True
        except Exception as e:
            self.logger.error(f"Error syncing to share: {str(e)}")
            return None

    def rsync_to_share(self, rsync_args=None, exclude_existing=None):
        """Synchronize files to share directory using rsync."""
        if not self.run_share_dir:
            self.logger.debug("run_share_dir not defined - skipping sync-ing ...")
            return None
            
        try:
            # Create destination directory if needed
            _dirname = os.path.dirname(self.run_share_dir)
            Path(_dirname).mkdir(parents=True, exist_ok=True)

            if not rsync_args:
                rsync_args = "-avug"

            if exclude_existing:
                rsync_args = f'{rsync_args} --ignore-existing'

            cmd_args = rsync_args.split() + [f"{self.exec_dir}/", f"{self.run_share_dir}"]
            
            # Using subprocess to run rsync
            result = subprocess.run(["rsync"] + cmd_args, 
                                   check=True, capture_output=True, text=True)
            self.logger.debug(f"Sync-ed to run share dir {self.run_share_dir}")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to sync to {self.run_share_dir}: {e.stderr}")
            return None
        except Exception as e:
            self.logger.error(f"Error during rsync: {str(e)}")
            return None

    def remap_app_vars(self):
        """Remap application variables with prefix to shorter names."""
        if not self.os_env_prefix:
            return None

        _split_char = f"{self.os_env_prefix}_"

        _add_values = {}
        keys_to_delete = []

        for _key, _value in self.inputargs.items():
            if _split_char not in _key:
                continue

            _mapped_key = _key.split(_split_char)[-1]

            _add_values[_mapped_key] = _value
            keys_to_delete.append(_key)

            self.logger.debug(f"mapped key {_key} value {_value}")

        for _mapped_key, _value in _add_values.items():
            self.inputargs[_mapped_key] = _value

        for key_to_delete in keys_to_delete:
            del self.inputargs[key_to_delete]

    @staticmethod
    def get_hash(_object):
        """Get hash of an object."""
        return get_hash(_object)

    def add_output(self, cmd=None, remove_empty=None, **results):
        """Add command output to the output collection."""
        try:
            _outputs = to_json(results["output"])
        except Exception:
            _outputs = None

        if not _outputs:
            return None

        if cmd:
            self.output.append(cmd)

        for _output in _outputs:
            if remove_empty and not _output:
                continue
            self.output.extend(_output)

    @staticmethod
    def to_json(output):
        """Convert output to JSON format."""
        return _to_json(output)

    @staticmethod
    def print_output(**kwargs):
        """Print output to standard output."""
        output = _to_json(kwargs["output"])

        try:
            if isinstance(output, bytes):
                output = output.decode()
        except Exception:
            print("could not convert output to string")

        try:
            if isinstance(output, str):
                output = output.split("\n")
        except Exception:
            print("could not convert output to list")

        print('_config0_begin_output')

        if isinstance(output, list):
            for _output in output:
                print(_output)
        else:
            print(output)

    def jsonfile_to_phases_info(self):
        """Load phases information from JSON file."""
        if not hasattr(self, "config0_phases_json_file"):
            self.logger.debug("jsonfile_to_phases_info - config0_phases_json_file not set")
            return None

        if not self.config0_phases_json_file:
            return None

        if not os.path.exists(self.config0_phases_json_file):
            return None

        try:
            self.phases_info = get_values_frm_json(json_file=self.config0_phases_json_file)
            return self.phases_info
        except Exception as e:
            self.logger.error(f"Error loading phases info from JSON: {str(e)}")
            return None

    def delete_phases_to_json_file(self):
        """Delete phases JSON file."""
        if not hasattr(self, "config0_phases_json_file"):
            self.logger.debug("delete_phases_to_json_file - config0_phases_json_file not set")
            return None

        if not self.config0_phases_json_file:
            return None

        if not os.path.exists(self.config0_phases_json_file):
            return None

        try:
            rm_rf(self.config0_phases_json_file)
            return True
        except Exception as e:
            self.logger.error(f"Error deleting phases JSON file: {str(e)}")
            return None

    def write_phases_to_json_file(self, content_json):
        """Write phases information to JSON file."""
        if not hasattr(self, "config0_phases_json_file"):
            self.logger.debug("write_phases_to_json_file - config0_phases_json_file not set")
            return None

        if not self.config0_phases_json_file:
            return None

        try:
            self.logger.debug(f"u4324: inserting retrieved data into {self.config0_phases_json_file}")
            return to_jsonfile(content_json, self.config0_phases_json_file)
        except Exception as e:
            self.logger.error(f"Error writing phases to JSON file: {str(e)}")
            return None

    def write_resource_to_json_file(self, resource, must_exist=None):
        """Write resource information to JSON file."""
        msg = "config0_resource_json_file needs to be set"

        if not hasattr(self, "config0_resource_json_file") or not self.config0_resource_json_file:
            if must_exist:
                raise Exception(msg)
            else:
                self.logger.debug(msg)
            return None

        try:
            self.logger.debug(f"u4324: inserting retrieved data into {self.config0_resource_json_file}")
            return to_jsonfile(resource, self.config0_resource_json_file)
        except Exception as e:
            self.logger.error(f"Error writing resource to JSON file: {str(e)}")
            return None

    def successful_output(self, **kwargs):
        """Print output and exit successfully."""
        self.print_output(**kwargs)
        exit(0)
        
    @staticmethod
    def clean_output(results, replace=True):
        """Clean and decode command output."""
        clean_lines = []

        if isinstance(results["output"], list):
            for line in results["output"]:
                try:
                    clean_lines.append(line.decode("utf-8"))
                except (AttributeError, UnicodeDecodeError):
                    clean_lines.append(line)
        else:
            try:
                clean_lines.append((results["output"].decode("utf-8")))
            except (AttributeError, UnicodeDecodeError):
                clean_lines.append(results["output"])

        if replace:
            results["output"] = "\n".join(clean_lines)

        return clean_lines

    def execute(self, cmd, **kwargs):
        """Execute command and return results."""
        return self.execute3(cmd, **kwargs)

    @staticmethod
    def execute3(cmd, **kwargs):
        """Execute command version 3."""
        return execute3(cmd, **kwargs)

    @staticmethod
    def execute2(cmd, **kwargs):
        """Execute command version 2 (alias for v3)."""
        return execute3(cmd, **kwargs)

    @staticmethod
    def execute4(cmd, **kwargs):
        """Execute command version 4."""
        return execute4(cmd, **kwargs)

    def cmd_failed(self, **kwargs):
        """Handle command failure and exit."""
        failed_message = kwargs.get("failed_message")

        if not failed_message:
            failed_message = "No failed message to output"

        self.logger.error(message=failed_message)
        exit(9)

    def _set_inputargs_to_false(self):
        """Convert 'False' string values in inputargs to boolean False."""
        for _k, _v in self.inputargs.items():
            if _v != "False":
                continue

            self.inputargs[_k] = False

    def _add_to_inputargs(self, ref, inputargs=None):
        """Add values to inputargs if not already present."""
        if not inputargs:
            return

        for _k, _v in inputargs.items():
            if _k in self.inputargs:
                continue

            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug(f"{ref} - added to inputargs {_k} -> {_v}")
            else:
                self.logger.debug(f'{ref} - added key "{_k}"')

            self.inputargs[_k] = _v

    def set_inputargs(self, **kwargs):
        """Set input arguments from various sources."""
        if kwargs.get("inputargs"):
            _inputargs = kwargs["inputargs"]
            self._add_to_inputargs("ref 34524-1", _inputargs)

        elif kwargs.get("json_input"):
            _inputargs = to_json(kwargs["json_input"], exit_error=True)
            self._add_to_inputargs("ref 34524-2", _inputargs)

        if kwargs.get("add_app_vars") and self.os_env_prefix:
            _inputargs = self.get_os_env_prefix_envs(remove_os_environ=False)
            self._add_to_inputargs("ref 34524-3", _inputargs)

        if kwargs.get("set_env_vars"):
            _inputargs = self.parse_set_env_vars(kwargs["set_env_vars"])
            self._add_to_inputargs("ref 34524-4", _inputargs)

        standard_env_vars = ["JOB_INSTANCE_ID",
                            "SCHEDULE_ID",
                            "RUN_ID",
                            "RESOURCE_TYPE",
                            "METHOD",
                            "PHASE"]

        _inputargs = self.parse_set_env_vars(standard_env_vars)
        self._add_to_inputargs("ref 34524-5", _inputargs)
        self._set_inputargs_to_false()

    @staticmethod
    def parse_set_env_vars(env_vars):
        """Parse environment variables and return as inputargs."""
        inputargs = {}

        for env_var in env_vars:
            if not os.environ.get(env_var.upper()):
                continue

            if os.environ.get(env_var.upper()) == "None":
                continue

            if os.environ.get(env_var.upper()) == "False":
                inputargs[env_var.lower()] = False
                continue

            inputargs[env_var.lower()] = os.environ[env_var.upper()]

        return inputargs

    def check_required_inputargs(self, **kwargs):
        """Check if required input arguments are present."""
        status = True
        required_keys = []

        _keys = kwargs.get("keys")

        if not _keys:
            return True

        for key in kwargs["keys"]:
            if key not in self.inputargs:
                required_keys.append(key)
                status = None

        if status:
            return True

        self.logger.aggmsg("These keys missing and need to be set:", new=True)
        self.logger.aggmsg("")
        self.logger.aggmsg(f"\tkeys found include: {list(self.inputargs.keys())}")
        self.logger.aggmsg("")

        for key in required_keys:
            if self.os_env_prefix:
                self.logger.aggmsg(f"\t{key} or Environmental Variable {key.upper()}/{self.os_env_prefix}_{key}")
            else:
                self.logger.aggmsg(f"\t{key} or Environmental Variable {key.upper()}")

        failed_message = self.logger.aggmsg("")
        self.cmd_failed(failed_message=failed_message)

    def check_either_inputargs(self, **kwargs):
        """Check if at least one of the specified keys is present."""
        _keys = kwargs.get("keys")

        if not _keys:
            return True

        for key in kwargs["keys"]:
            if key in self.inputargs:
                return True

        self.logger.aggmsg("one of these keys need to be set:", new=True)
        self.logger.aggmsg("")

        for key in kwargs["keys"]:
            if self.os_env_prefix:
                self.logger.aggmsg(f"\t{key} or Environmental Variable {key.upper()}/{self.os_env_prefix}_{key}")
            else:
                self.logger.aggmsg(f"\t{key} or Environmental Variable {key.upper()}")
        failed_message = self.logger.aggmsg("")
        self.cmd_failed(failed_message=failed_message)

    def create_build_envfile(self, encrypt=None, openssl=True):
        """
        Create build environment file, potentially encrypted.
        Uses stateful_id for encryption key.
        """
        if not self.build_env_vars:
            return None

        try:
            ssm_env_vars = {}
            build_env_vars = deepcopy(self.build_env_vars)

            if "ssm_name" in build_env_vars:
                ssm_env_vars["ssm_name"] = str(build_env_vars["ssm_name"])
                del build_env_vars["ssm_name"]

            if "SSM_NAME" in build_env_vars:
                ssm_env_vars["SSM_NAME"] = str(build_env_vars["SSM_NAME"])
                del build_env_vars["SSM_NAME"]

            base_file_path = os.path.join(self.run_share_dir, self.app_dir)

            # Ensure directory exists
            Path(base_file_path).mkdir(parents=True, exist_ok=True)

            if build_env_vars:
                create_envfile(build_env_vars,
                              b64=True,
                              file_path=f"{base_file_path}/build_env_vars.env.enc")

            if ssm_env_vars:
                create_envfile(ssm_env_vars,
                              b64=True,
                              file_path=f"{base_file_path}/ssm.env.enc")

            return True
        except Exception as e:
            self.logger.error(f"Error creating build envfile: {str(e)}")
            return None

    def _write_local_log(self):
        """Write output to local log file."""
        try:
            cli_log_file = f'/tmp/{self.stateful_id}.cli.log'

            with open(cli_log_file, "w") as f:
                f.write(self.final_output)

            print(f'local log file here: {cli_log_file}')
            return True
        except Exception as e:
            self.logger.error(f"Error writing local log: {str(e)}")
            return None

    def eval_log(self, results, local_log=None):
        """Evaluate and process command log output."""
        if not results.get("output"):
            return None

        self.clean_output(results, replace=True)
        self.final_output = results["output"]
        self.append_log(self.final_output)
        del results["output"]

        if local_log:
            try:
                self._write_local_log()
            except Exception:
                self.logger.debug("could not write local log")

        print(self.final_output)
        return self.final_output

    def eval_failure(self, results, method):
        """Evaluate command failure and handle appropriately."""
        if results.get("status") is not False:
            return None

        self.eval_log(results)

        print("")
        print("-"*32)
        failed_message = f"{self.app_name} {method} failed here {self.run_share_dir}!"
        print(failed_message)
        print("-"*32)
        print("")
        exit(43)

    def _get_next_phase(self, method="create", **json_info):
        """Get the next phase to execute based on completed phases."""
        results = json_info["results"]
        method_phases_params = b64_decode(json_info["phases_params_hash"])[method]

        completed = []

        for phase_info in results["phases_info"]:
            if phase_info.get("status"):
                completed.append(phase_info["name"])

        for phase_param in method_phases_params:
            if phase_param["name"] in completed:
                self.logger.debug(f'phase "{phase_param["name"]}" completed')
                continue
            self.logger.debug(f'Next phase to run: "{phase_param["name"]}"')
            return phase_param

        # Clean up run directory
        try:
            shutil.rmtree(self.run_share_dir, ignore_errors=True)
        except Exception as e:
            self.logger.warn(f"Error cleaning up run directory: {str(e)}")

        self.logger.error("Cannot determine next phase to run - reset")
        raise Exception("Cannot determine next phase to run")

    def set_cur_phase(self):
        """Set the current execution phase."""
        self.jsonfile_to_phases_info()

        if self.phases_info and self.phases_info.get("inputargs"):
            self.set_class_vars(self.phases_info["inputargs"])

        if self.phases_info and self.phases_info.get("phases_params_hash"):
            self.phases_params_hash = self.phases_info["phases_params_hash"]
        else:
            self.phases_params_hash = os.environ.get("PHASES_PARAMS_HASH")

        if not self.phases_info and not self.phases_params_hash:
            self.logger.debug("Phase are not implemented")
            return None

        try:
            if not self.phases_params_hash and self.phases_params:
                self.phases_params_hash = b64_encode(self.phases_params)
            elif not self.phases_params and self.phases_params_hash:
                self.phases_params = b64_decode(self.phases_params_hash)

            if self.phases_info:
                self.current_phase = self._get_next_phase(self.method,
                                                        **self.phases_info)
            elif self.phases_params_hash:
                self.logger.json(self.phases_params)
                self.current_phase = self.phases_params[self.method][0]  # first phase

            self.phase = self.current_phase["name"]
            return self.current_phase
        except Exception as e:
            self.logger.error(f"Error setting current phase: {str(e)}")
            return None