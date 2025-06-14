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
    FORCE_NEW_EXECUTION: Force a new execution regardless of existing ones
"""

import os
import jinja2
import glob
import json
import shutil
import hashlib
from pathlib import Path
from copy import deepcopy
from time import time

from config0_publisher.utilities import id_generator2
from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import print_json
from config0_publisher.utilities import to_json
from config0_publisher.utilities import to_jsonfile
from config0_publisher.utilities import get_hash
from config0_publisher.utilities import eval_str_to_join
from config0_publisher.shellouts import execute4
from config0_publisher.shellouts import execute3
from config0_publisher.serialization import create_envfile
from config0_publisher.templating import list_template_files
from config0_publisher.variables import EnvVarsToClassVars
from config0_publisher.resource.phases import ResourcePhases

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
from config0_publisher.resource.aws_executor import aws_executor
from config0_publisher.resource.aws_executor import AWSAsyncExecutor

#############################################

def _to_json(output):
    if isinstance(output, dict):
        return output

    try:
        _output = to_json(output)
        if not _output:
            raise Exception("output is None")
        if not isinstance(_output, dict):
            raise Exception("output is not a dict")
        output = _output
    except:
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            print("Could not convert output to json")

    return output

class ResourceCmdHelper(ResourcePhases):

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

        # testtest456
        #SyncToShare.__init__(self)

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

        ResourcePhases.__init__(self)

        # set specified env variables
        self._set_env_vars(env_vars=kwargs.get("env_vars"),
                           clobber=True)

        self._set_os_env_prefix()
        self._set_app_params()

        self._init_syncvars(**kwargs)
        self._finalize_set_vars()

        self._set_build_timeout()
        self._set_aws_region()

        # ref 34532453245
        self.final_output = None
        
        # Set force_new_execution from environment variable if present
        if os.environ.get("FORCE_NEW_EXECUTION"):
            self.force_new_execution = True
        else:
            self.force_new_execution = kwargs.get("force_new_execution", False)

        # testtest456 - remove
        #self.force_new_execution = True

    def _set_execution_id(self,**kwargs):

        self.execution_id = os.environ.get("EXECUTION_ID", None)

        if not self.execution_id:
            self.execution_id = kwargs.get("execution_id",id_generator2())

        if not self.stateful_id:
            self.execution_id_path = f'logs/unknown/{self.execution_id}'
        else:
            self.execution_id_path = f'logs/{self.stateful_id}/{self.execution_id}'

    def _set_build_timeout(self):
        if hasattr(self, "build_timeout") and self.build_timeout:
            return

        try:
            self.build_timeout = int(os.environ.get("BUILD_TIMEOUT"))
        except:
            self.build_timeout = None

        if self.build_timeout:
            return

        try:
            self.build_timeout = int(os.environ.get("TIMEOUT")) - 90
        except:
            self.build_timeout = None

        if self.build_timeout:
            return

        self.build_timeout = 500

    def _set_aws_region(self):
        self.aws_backend_region = os.environ.get("AWS_BACKEND_REGION") or "us-east-1"

        if hasattr(self, "aws_region") and self.aws_region:
            return

        self.aws_region = os.environ.get("AWS_DEFAULT_REGION")

        if self.aws_region:
            return

        self.aws_region = "us-east-1"

    def _finalize_set_vars(self):
        self._set_stateful_params()
        self._set_exec_dir()
        self._set_docker_settings()
        self._set_mod_env_vars()
        self._get_docker_env_filepath()

        self._set_special_keywords_classvars()  # special keywords ... chrootfiles_dest_dir

        # execute it final time to synchronize class vars set
        self.set_class_vars()

        # testtest456 not sure the below is needed
        self.syncvars.set()

        self._set_env_vars(env_vars=self.syncvars.class_vars)  # synchronize to env variables
        self._set_json_files()

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            try:
                self._print_out_key_class_vars()
            except:
                self.logger.debug("could not print out debug class vars")

        #self._debug_print_out_key_class_vars()

    def _set_json_files(self):
        if not hasattr(self, "config0_resource_json_file") or not self.config0_resource_json_file:
            self.config0_resource_json_file = os.environ.get("CONFIG0_RESOURCE_JSON_FILE")

        if not self.config0_resource_json_file:
            try:
                self.config0_resource_json_file = os.path.join(self.stateful_dir,
                                                               f"resource-{self.stateful_id}.json")
            except:
                self.config0_resource_json_file = None

        self.logger.debug(f'u4324: CONFIG0_RESOURCE_JSON_FILE "{self.config0_resource_json_file}"')

        if not hasattr(self, "config0_phases_json_file") or not self.config0_phases_json_file:
            self.config0_phases_json_file = os.environ.get("CONFIG0_PHASES_JSON_FILE")

        if not self.config0_phases_json_file:
            try:
                self.config0_phases_json_file = os.path.join(self.stateful_dir,
                                                             f"phases-{self.stateful_id}.json")
            except:
                self.config0_phases_json_file = None

        self.logger.debug(f'u4324: CONFIG0_PHASES_JSON_FILE "{self.config0_phases_json_file}"')

    def _debug_print_out_key_class_vars(self):
        for _k, _v in self.syncvars.class_vars.items():
            try:
                self.logger.debug(f"{_k} -> {_v}")
            except:
                self.logger.warn(f"could not print class vars {_k}")

    def _set_special_keywords_classvars(self):
        """
        # below not currently used but may be in future
        chrootfiles_dest_dir = self.syncvars.class_vars.get("chrootfiles_dest_dir")
        working_dir = self.syncvars.class_vars.get("working_dir")
        """
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
                exp = f'self.{key}=None'
                exec(exp)
            else:
                self.syncvars.class_vars[key] = run_share_dir

    def _init_syncvars(self, **kwargs):
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
            "output_bucket"
        ]

        default_values = {
            "share_dir": "/var/tmp/share",
            "run_share_dir": None,
            "tmp_bucket": None,
            "log_bucket": None,
            "output_bucket": None,
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
        if not class_vars:
            class_vars = self.syncvars.class_vars

        for _k, _v in class_vars.items():
            # check is the class vars already exists
            # and if not None/False, skip
            if hasattr(self, _k) and getattr(self, _k):
                continue

            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug(f" ## variable set: {_k} -> {_v}")

            if _v is None:
                exp = f"self.{_k}=None"
            elif _v is False:
                exp = f"self.{_k}=False"
            elif _v is True:
                exp = f"self.{_k}=True"
            else:
                exp = f'self.{_k}="{_v}"'

            exec(exp)

    def _set_env_vars(self, env_vars=None, clobber=False):
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
        if self.os_env_prefix: 
            return

        if self.app_name == "terraform":
            self.os_env_prefix = "TF_VAR"
        elif self.app_name == "ansible":
            self.os_env_prefix = "ANS_VAR"

    def _get_template_vars(self, **kwargs):
        # if the app_template_vars is provided, we use it, otherwise, we
        # assume it is the <APP_NAME>_EXEC_TEMPLATE_VARS
        _template_vars = kwargs.get("app_template_vars")

        if not _template_vars and self.app_name:
            _template_vars = f"{self.app_name}_EXEC_TEMPLATE_VARS"

        if not os.environ.get(_template_vars.upper()): 
            _template_vars = "ED_EXEC_TEMPLATE_VARS"

        if os.environ.get(_template_vars.upper()):
            return [_var.strip() for _var in os.environ.get(_template_vars.upper()).split(",")]

        if not self.os_env_prefix: 
            return

        # get template_vars e.g. "ANS_VAR_<var>"
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
        try:
            self.destroy_env_vars = eval(self.destroy_env_vars)
        except:
            self.destroy_env_vars = None

        self.syncvars.class_vars["destroy_env_vars"] = self.destroy_env_vars

        try:
            self.validate_env_vars = eval(self.validate_env_vars)
        except:
            self.validate_env_vars = None

        self.syncvars.class_vars["validate_env_vars"] = self.validate_env_vars

    def _set_docker_settings(self):
        # docker image explicitly set
        if self.docker_image:
            return

        # we set default by app_name
        if not self.app_name:
            return

        # terraform typically does not
        # use docker runtime
        if self.app_name == "terraform":
            return

        # docker image not set but app_name is set
        self.docker_image = f"config0/{self.app_name}-run-env"
        self.syncvars.class_vars["docker_image"] = self.docker_image

    def _mkdir(self, dir_path):
        if os.path.exists(dir_path): 
            return

        Path(dir_path).mkdir(parents=True, exist_ok=True)

    def _set_stateful_params(self):
        self.postscript_path = None
        self.postscript = None

        if not self.stateful_id: 
            return

        if not self.run_share_dir:
            self.run_share_dir = os.path.join(self.share_dir,
                                              self.stateful_id)

            self.syncvars.class_vars["run_share_dir"] = self.run_share_dir

        self._mkdir(self.run_share_dir)

        return

    def _set_app_params(self):
        if not self.app_name:
            return

        # app_name is set at this point

        # set app_dir
        if not self.app_dir:
            self.app_dir = os.environ.get(f"{self.app_name.upper()}_DIR")

        if not self.app_dir:
            self.app_dir = f"var/tmp/{self.app_name}"

        if self.app_dir[0] == "/": 
            self.app_dir = self.app_dir[1:]

        # this can be overided by inherited class
        if not self.shelloutconfig:
            self.shelloutconfig = f"config0-publish:::{self.app_name}::resource_wrapper"

    def _set_exec_dir(self):
        if self.stateful_id:
            self.exec_dir = self.run_share_dir
        else:
            self.exec_dir = self.exec_base_dir

        # ref 453646
        # overide the exec_dir set from _set_stateful_params
        # e.g. /var/tmp/share/ABC123/var/tmp/ansible

        if self.app_dir:
            self.exec_dir = os.path.join(self.exec_dir,
                                         self.app_dir)

        self.syncvars.class_vars["exec_dir"] = self.exec_dir

        self._mkdir(self.exec_dir)

        if hasattr(self, "exec_dir") and self.exec_dir:
            self.template_dir = f"{self.exec_dir}/_config0_templates"

            # ref 34532045732
            self.resources_dir = os.path.join(self.exec_dir,
                                              "config0_resources")  

    def _get_resource_files(self):
        self.logger.debug(f"getting json files from resources_dir {self.resources_dir}")

        if not os.path.exists(self.resources_dir): 
            self.logger.debug(f"DOES NOT EXIST resources_dir {self.resources_dir}")
            return

        _files = glob.glob(f"{self.resources_dir}/*.json")

        self.logger.debug(_files)

        if not _files: 
            return
        
        resources = []

        for _file in _files:
            try:
                _values = json.loads(open(_file, "r").read())
                resources.append(_values)
            except:
                self.logger.warn(f"could not retrieve resource json contents from {_file}")

        if not resources: 
            return 

        if len(resources) == 1: 
            return resources[0]

        return resources

    def get_os_env_prefix_envs(self, remove_os_environ=True):
        """
        get os env prefix vars e.g. TF_VAR_ipadddress and return
        the variables as lowercase without the prefix
        e.g. ipaddress
        """

        if not self.os_env_prefix:
            return {}

        _split_key = f"{self.os_env_prefix}_"
        inputargs = {}

        for i in os.environ.keys():
            if self.os_env_prefix not in i: 
                continue

            _var = i.split(_split_key)[1].lower()
            inputargs[_var] = os.environ[i]

            if remove_os_environ:
                del os.environ[i]

        return inputargs

    def get_app_env_keys(self):
        if not self.os_env_prefix:
            return {}

        try:
            _env_keys = [_key for _key in os.environ.keys() if self.os_env_prefix in _key]
        except:
            _env_keys = None

        self.logger.debug_highlight(f'app_env_keys "{_env_keys}" for os_env_prefix "{self.os_env_prefix}"')

        return _env_keys

    def insert_os_env_prefix_envs(self, env_vars, exclude_vars=None):
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

            if not _env_key: 
                continue

            if _env_value in ["False", "false", "null", False]: 
                _env_value = "false"

            if _env_value in ["True", "true", True]: 
                _env_value = "true"

            env_vars[_env_key] = _env_value

    def append_log(self, log):
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
            except:
                _str = None
        else:
            _str = None

        if _str:
            output = _str
        else:
            output = log

        if append:
            with open(logfile, "a") as file:
                file.write("#"*32)
                file.write("\n# append log\n")
                file.write("#"*32)
                file.write("\n")
                file.write(output)
                file.write("\n")
                file.write("#"*32)
                file.write("\n")
        else:
            with open(logfile, "w") as file:
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
        output = _to_json(resources)
        print('_config0_begin_output')
        print(output)
        print('_config0_end_output')

        return

    def _get_docker_env_filepath(self):
        _docker_env_file = self.get_env_var("DOCKER_ENV_FILE",
                                            default=".env")

        if not self.run_share_dir:
            return

        try:
            self.docker_env_file = os.path.join(self.run_share_dir,
                                                _docker_env_file)
        except:
            self.docker_env_file = None

        self.syncvars.class_vars["docker_env_file"] = self.docker_env_file

        return self.docker_env_file

    # referenced and related to: dup dhdskyeucnfhrt2634521
    def get_env_var(self, variable, default=None, must_exists=None):
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

        if default:
            return default

        if not must_exists:
            return

        raise Exception(f"{variable} does not exist")

    @staticmethod
    def print_json(values):
        print_json(values)

    def templify(self, **kwargs):
        clobber = kwargs.get("clobber")
        _template_vars = self._get_template_vars(**kwargs)

        if not _template_vars:
            self.logger.debug_highlight("template vars is not set or empty")
            return

        self.logger.debug_highlight(f"template vars {_template_vars} not set or empty")

        if not self.template_dir:
            self.logger.warn("template_dir not set (None) - skipping templating")
            return

        template_files = list_template_files(self.template_dir)

        if not template_files:
            self.logger.warn(f"template_files in directory {self.template_dir} empty - skipping templating")
            return

        for _file_stats in template_files:
            template_filepath = _file_stats["file"]

            file_dir = os.path.join(self.exec_dir,
                                    _file_stats["directory"])

            file_path = os.path.join(self.exec_dir,
                                     _file_stats["directory"],
                                     _file_stats["filename"].split(".ja2")[0])

            self._mkdir(file_dir)

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

                if self.os_env_prefix:
                    if self.os_env_prefix in _var:
                        _key = _var.split(_split_char)[1]
                        _value = os.environ.get(_var)
                    else:
                        _key = str(f"{self.os_env_prefix}_{_var}")
                        _value = os.environ.get(_key)

                    if _value: _mapped_key = _key

                if not _value:
                    _value = os.environ.get(str(_var))
                    if _value: _mapped_key = _var

                if not _value:
                    _value = os.environ.get(str(_var.upper()))
                    if _value: _mapped_key = _var.upper()

                self.logger.debug("")
                self.logger.debug(f"mapped_key {_mapped_key}")
                self.logger.debug(f"var {_var}")
                self.logger.debug(f"value {_value}")
                self.logger.debug("")

                if not _value: 
                    self.logger.warn(f"skipping templify var {_var}")
                    continue

                value = _value.replace("'", '"')

                # include both uppercase and regular keys
                template_vars[_mapped_key] = value
                template_vars[_mapped_key.upper()] = value

            self.logger.debug("")
            self.logger.debug(f"template_vars {template_vars}")
            self.logger.debug("")

            template_loader = jinja2.FileSystemLoader(searchpath="/")
            template_env = jinja2.Environment(loader=template_loader)
            template = template_env.get_template(template_filepath)
            output_text = template.render(template_vars)
            writefile = open(file_path, "w")
            writefile.write(output_text)
            writefile.close()

        return True

    def write_key_to_file(self, **kwargs):
        """
        Writing the value of a key in kwargs to a file
        """
        key = kwargs["key"]
        filepath = kwargs["filepath"]
        split_char = kwargs.get("split_char")
        add_return = kwargs.get("add_return", True)
        copy_to_share = kwargs.get("copy_to_share")
        deserialize = kwargs.get("deserialize")

        try:
            permission = int(kwargs.get("permission"))
        except:
            permission = 0o400  # Default permission for SSH private keys (octal notation)

        if not self.inputargs.get(key):
            return

        _value = self.inputargs[key]

        if deserialize:
            _value = b64_decode(_value)

        if split_char is None: 
            _lines = _value
        elif split_char == "return":
            _lines = _value.split('\\n')
        else:
            _lines = _value

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

    def copy_file_to_share(self, srcfile, dst_subdir=None):
        if not self.run_share_dir: 
            self.logger.debug("run_share_dir not defined - skipping sync-ing ...")
            return
            
        # Create destination directory if needed
        _dirname = os.path.dirname(self.run_share_dir)
        self._mkdir(_dirname)

        _file_subpath = os.path.basename(srcfile)

        if dst_subdir:
            _file_subpath = f"{dst_subdir}/{_file_subpath}"
            # Create dst_subdir if needed
            dst_path = os.path.join(self.run_share_dir, dst_subdir)
            self._mkdir(dst_path)

        dstfile = f"{self.run_share_dir}/{_file_subpath}"

        # Copy file
        shutil.copy2(srcfile, dstfile)

    def remap_app_vars(self):
        if not self.os_env_prefix: 
            return

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
        return get_hash(_object)

    def add_output(self, cmd=None, remove_empty=None, **results):
        try:
            _outputs = to_json(results["output"])
        except:
            _outputs = None

        if not _outputs: 
            return

        if cmd: 
            self.output.append(cmd)

        for _output in _outputs: 
            if remove_empty and not _output: continue
            self.output.extend(_output)

    @staticmethod
    def to_json(output):
        return _to_json(output)

    @staticmethod
    def print_output(**kwargs):
        output = _to_json(kwargs["output"])

        try:
            if isinstance(output, bytes):
                output = output.decode()
        except:
            print("could not convert output to string")

        try:
            if isinstance(output, str):
                output = output.split("\n")
        except:
            print("could not convert output to list")

        print('_config0_begin_output')

        if isinstance(output, list):
            for _output in output:
                print(_output)
        else:
            print(output)

    def write_resource_to_json_file(self, resource, must_exist=None):
        msg = "config0_resource_json_file needs to be set"

        if not hasattr(self, "config0_resource_json_file") or not self.config0_resource_json_file:
            if must_exist:
                raise Exception(msg)
            else:
                self.logger.debug(msg)
            return

        self.logger.debug(f"u4324: inserting retrieved data into {self.config0_resource_json_file}")

        to_jsonfile(resource,
                    self.config0_resource_json_file)

    def successful_output(self, **kwargs):
        self.print_output(**kwargs)
        exit(0)
        
    @staticmethod
    def clean_output(results, replace=True):
        clean_lines = []

        if isinstance(results["output"], list):
            for line in results["output"]:
                try:
                    clean_lines.append(line.decode("utf-8"))
                except:
                    clean_lines.append(line)
        else:
            try:
                clean_lines.append((results["output"].decode("utf-8")))
            except:
                clean_lines.append(results["output"])

        if replace:
            results["output"] = "\n".join(clean_lines)

        return clean_lines

    def execute(self, cmd, **kwargs):
        results = self.execute3(cmd, **kwargs)

        return results

    @staticmethod
    def execute3(cmd, **kwargs):
        return execute3(cmd, **kwargs)

    @staticmethod
    def execute2(cmd, **kwargs):
        return execute3(cmd, **kwargs)

    @staticmethod
    def execute4(cmd, **kwargs):
        return execute4(cmd, **kwargs)

    def cmd_failed(self, **kwargs):
        failed_message = kwargs.get("failed_message")

        if not failed_message: 
            failed_message = "No failed message to outputted"

        self.logger.error(message=failed_message)
        exit(9)

    def _set_inputargs_to_false(self):
        for _k, _v in self.inputargs.items():
            if _v != "False": 
                continue

            self.inputargs[_k] = False

    def _add_to_inputargs(self, ref, inputargs=None):
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
        _inputargs = None

        if kwargs.get("inputargs"):
            _inputargs = kwargs["inputargs"]
            self._add_to_inputargs("ref 34524-1", _inputargs)

        elif kwargs.get("json_input"):
            _inputargs = to_json(kwargs["json_input"],
                                     exit_error=True)
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

    # This can be replaced by the inheriting class
    @staticmethod
    def parse_set_env_vars(env_vars):
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
        status = True
        required_keys = []

        _keys = kwargs.get("keys")

        if not _keys: 
            return 

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
        _keys = kwargs.get("keys")

        if not _keys: 
            return 

        for key in kwargs["keys"]:
            if key in self.inputargs: 
                return 

        self.logger.aggmsg("one of these keys need to be set:", new=True)
        self.logger.aggmsg("")

        for key in kwargs["keys"]:
            if self.os_env_prefix:
                self.logger.aggmsg(f"\t{key} or Environmental Variable {key.upper()}/{self.os_env_prefix}_{key}")
            else:
                self.logger.aggmsg(f"\t{key} or Environmental Variable {key.upper()}")
        failed_message = self.logger.aggmsg("")
        self.cmd_failed(failed_message=failed_message)

    # testtest456
    # ref 4354523
    #def create_build_envfile(self):
    def create_build_envfile(self, encrypt=None, openssl=True):
        """
        we use stateful_id for the encrypt key
        """

        if not self.build_env_vars:
            return

        ssm_env_vars = {}

        build_env_vars = deepcopy(self.build_env_vars)

        if "ssm_name" in build_env_vars:
            ssm_env_vars["ssm_name"] = str(build_env_vars["ssm_name"])
            del build_env_vars["ssm_name"]

        if "SSM_NAME" in build_env_vars:
            ssm_env_vars["SSM_NAME"] = str(build_env_vars["SSM_NAME"])
            del build_env_vars["SSM_NAME"]

        base_file_path = os.path.join(self.run_share_dir,
                                      self.app_dir)

        self._mkdir(base_file_path)

        if build_env_vars:
            create_envfile(build_env_vars,
                           b64=True,
                           file_path=f"{base_file_path}/build_env_vars.env.enc")

        if ssm_env_vars:
            create_envfile(ssm_env_vars,
                           b64=True,
                           file_path=f"{base_file_path}/ssm.env.enc")

        return True

    def _write_local_log(self):
        cli_log_file = f'/tmp/{self.stateful_id}.cli.log'

        with open(cli_log_file, "w") as f:
            f.write(self.final_output)

        print(f'local log file here: {cli_log_file}')

        return True

    def eval_log(self, results, local_log=None):
        if not results.get("output"):
            return

        self.clean_output(results, replace=True)
        self.final_output = results["output"]
        self.append_log(self.final_output)
        del results["output"]

        # ref 34532453245
        if local_log:
            try:
                self._write_local_log()
            except:
                self.logger.debug("could not write local log")

        print(self.final_output)

    def eval_failure(self, results, method):
        if results.get("status") is not False:
            return

        #self.eval_log(results)

        print("")
        print("-"*32)
        failed_message = f"{self.app_name} {method} failed here {self.run_share_dir}!"
        print(failed_message)
        print("-"*32)
        print("")
        exit(43)

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

        return cinputargs

    def _set_build_method(self):
        """Determines whether to use CodeBuild or Lambda for execution"""

        if os.environ.get("USE_CODEBUILD"):  # longer than 900 seconds
            self.build_method = "codebuild"
        elif os.environ.get("USE_LAMBDA"):  # shorter than 900 seconds
            self.build_method = "lambda"
        elif self.method in ["validate", "check"]:
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

    def _exec_in_aws(self, method="create"):
        """Executes Terraform command in AWS with execution tracking"""

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

        #executor.clear_execution()

        # Use the appropriate build method and prepare invocation configuration
        if self.build_method == "lambda":
            _awsbuild = Lambdabuild(**cinputargs)
            invocation_config = _awsbuild.pre_trigger()

            # testtest456
            print('h0'*32)
            self.logger.json(cinputargs)
            print('h1'*32)
            self.logger.json(invocation_config)
            print('h2'*32)

            results = executor.exec_lambda(
                **invocation_config)

        elif self.build_method == "codebuild":
            _awsbuild = Codebuild(**cinputargs)
            inputargs = _awsbuild.pre_trigger()

            results = executor.exec_codebuild(**inputargs)
            
        else:
            return False
        
        if method == "destroy":
            try:
                os.chdir(self.cwd)
            except (FileNotFoundError, PermissionError) as e:
                os.chdir("/tmp")

        self.logger.debug(f'tf_status: "{results.get("tf_status")}"')
        self.logger.debug(f'tf_exitcode: "{results.get("tf_exitcode")}"')

        if results.get("tf_status"):
            results["status"] = results["tf_status"]

        if results.get("tf_exitcode"):
            results["exitcode"] = results["tf_exitcode"]

        self.eval_failure(results, method)
        return results

    def create(self):
        """Creates Terraform resources"""

        if not self.stateful_id:
            self.logger.error("STATEFUL_ID needs to be set")

        # If we render template files, we don't create tfvars file
        if not self.templify(app_template_vars="TF_EXEC_TEMPLATE_VARS", **self.inputargs):
            self.exclude_tfvars = self._create_terraform_tfvars()

        if not os.path.exists(self.exec_dir):
            raise Exception(f"terraform directory must exist at {self.exec_dir} when creating tf")

        self._set_runtime_env_vars(method="create")
        self.create_aws_tf_backend()

        # Submit and run required env file
        self.create_build_envfile()

        if self.build_method == "codebuild":
            _use_codebuild = True
        else:
            _use_codebuild = None

        #pre_creation = self._exec_in_aws(method="pre-create")
        #if not pre_creation.get("status"):
        #    self.logger.debug("f1a" * 32)
        #    self.logger.error("pre-create failed")
        #    return pre_creation

        if _use_codebuild:
            self.build_method = "codebuild"

        tf_results = self._exec_in_aws(method="create")

        # testtest456
        self.logger.debug("f2"*32)
        self.logger.json(tf_results)
        self.logger.debug("f3"*32)

        # Should never get this far if execution failed
        # because eval_failure should exit out
        if not tf_results.get("status"):
            return tf_results

        if hasattr(self, "post_create") and callable(self.post_create):
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
        else:
            usage()
            print(f'Method "{self.method}" not supported!')
            exit(4)

        # testtest456
        self.logger.debug("t0"*32)
        self.logger.json(tf_results)
        self.logger.debug("t0"*32)

        # Evaluation of log should be at the end
        # outside of _exec_in_aws
        #self.eval_log(tf_results, local_log=True)