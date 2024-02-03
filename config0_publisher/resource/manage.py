#!/usr/bin/env python
#

import os
import jinja2
import glob
import json
from time import sleep

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
from config0_publisher.resource.codebuild import Codebuild
from config0_publisher.resource.lambdabuild import Lambdabuild
from config0_publisher.variables import EnvVarsToClassVars
#from config0_publisher.variables import SyncClassVarsHelper

# ref 34532045732
def to_jsonfile(values,filename,exec_dir=None):

    if not exec_dir: 
        exec_dir = os.getcwd()

    file_dir = os.path.join(exec_dir,
                            "config0_resources")

    file_path = os.path.join(file_dir,
                             filename)

    if not os.path.exists(file_dir):
        os.system(f"mkdir -p {file_dir}")

    try:
        with open(file_path,"w") as f:
            f.write(json.dumps(values))
        status = True
        print(f"Successfully wrote contents to {file_path}")
    except:
        print(f"Failed to write contents to {file_path}")
        status = False

    return status

def _to_json(output):

    if isinstance(output,dict):
        return output

    try:
        _output = to_json(output)
        if not _output:
            raise Exception("output is None")
        if not isinstance(_output,dict):
            raise Exception("output is not a dict")
        output = _output
    except:
        print("Could not convert output to json")

    return output

class MissingEnvironmentVariable(Exception):
    pass

class ResourceCmdHelper:

    def __init__(self,**kwargs):

        '''
        # stateful_id = abc123
        # run_dir -> exec_base_dir - e.g. /tmp/ondisktmp/abc123
        # app_dir -> exec_dir - e.g. var/tmp/ansible
        # share_dir - share directory with docker or execution container - e.g. /var/tmp/share
        # run_share_dir - share directory with stateful_id - e.g. /var/tmp/share/ABC123
        '''

        # testtest456
        raise Exception('hoho')

        self.classname = 'ResourceCmdHelper'
        self.logger = Config0Logger(self.classname)
        self.logger.debug("Instantiating %s" % self.classname)

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

        self.phases_params_hash = kwargs.get("phases_params_hash")
        self.phases_params = kwargs.get("phases_params")

        self.phases_info = None
        self.phase = None  # can be "run" since will only one phase
        self.current_phase = None

        self._set_phases_params()

        # set specified env variables
        self._set_env_vars(env_vars=kwargs.get("env_vars"),
                           clobber=True)

        self._set_os_env_prefix(**kwargs)
        self._set_app_params(**kwargs)
        
        self._init_syncvars(**kwargs)
        self._finalize_set_vars()

        self._set_build_timeout()
        self._set_aws_region()

    def _set_build_timeout(self):

        if hasattr(self,"build_timeout") and self.build_timeout:
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

        if hasattr(self,"aws_region") and self.aws_region:
            return

        self.aws_region = os.environ.get("AWS_REGION")

        if self.aws_region:
            return

        self.aws_region = os.environ.get("AWS_DEFAULT_REGION")

        if self.aws_region:
            return

        self.aws_region = "us-east-1"

    def _set_phases_params(self):

        if self.phases_params_hash:
            return

        if self.phases_params:
            self.phases_params_hash = b64_encode(self.phases_params)
            return

        if os.environ.get("PHASES_PARAMS_HASH"):
            self.phases_params_hash = os.environ.get("PHASES_PARAMS_HASH")
            return

    def init_phase_run(self):

        if not self.current_phase:
            return

        try:
            timewait = int(self.current_phase["timewait"])
        except:
            timewait = None

        if not timewait:
            return

        sleep(timewait)

    def get_phase_inputargs(self):

        if not self.current_phase:
            return

        try:
            inputargs = self.current_phase["inputargs"]
        except:
            inputargs = {}

        return inputargs

    def _finalize_set_vars(self):

        self._set_stateful_params()
        self._set_exec_dir()
        self._set_docker_settings()
        self._set_mod_env_vars()
        self._get_docker_env_filepath()
        self._set_special_keywords_classvars()  # special keywords for chrootfiles_dest_dir

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

        if not hasattr(self,"config0_resource_json_file") or not self.config0_resource_json_file:
            self.config0_resource_json_file = os.environ.get("CONFIG0_RESOURCE_JSON_FILE")

        if not hasattr(self,"config0_phases_json_file") or not self.config0_phases_json_file:
            self.config0_phases_json_file = os.environ.get("CONFIG0_PHASES_JSON_FILE")

        if not self.config0_resource_json_file:
            try:
                self.config0_resource_json_file = os.path.join(self.stateful_dir,
                                                          f"resource-{self.stateful_id}.json")
            except:
                self.config0_resource_json_file = None

        self.logger.debug(f'u4324: CONFIG0_RESOURCE_JSON_FILE "{self.config0_resource_json_file}"')

        if not self.config0_phases_json_file:
            try:
                self.config0_phases_json_file = os.path.join(self.stateful_dir,
                                                        f"phases-{self.stateful_id}.json")
            except:
                self.config0_phases_json_file = None

        self.logger.debug(f'u4324: CONFIG0_PHASES_JSON_FILE "{self.config0_phases_json_file}"')

    def _debug_print_out_key_class_vars(self):

        for _k,_v in self.syncvars.class_vars.items():
            try:
                self.logger.debug(f"{_k} -> {_v}")
            except:
                self.logger.warn(f"could not print class vars {_k}")

    def _set_special_keywords_classvars(self):

        chrootfiles_dest_dir = self.syncvars.class_vars.get("chrootfiles_dest_dir")
        working_dir = self.syncvars.class_vars.get("working_dir")
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

    def _init_syncvars(self,**kwargs):

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
            "docker_runtime",
            "docker_exec_env",
            "docker_image",
            "mod_execgroup",
            "destroy_env_vars",
            "validate_env_vars"
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
            "docker_runtime": None,
            "docker_exec_env": None,
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

    def set_class_vars(self,class_vars=None):

        if not class_vars:
            class_vars = self.syncvars.class_vars

        for _k,_v in class_vars.items():
            if _v is None:
                exp = f"self.{_k}=None"
            elif _v is False:
                exp = f"self.{_k}=False"
            elif _v is True:
                exp = f"self.{_k}=True"
            else:
                exp = f'self.{_k}="{_v}"'

            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug(f" ## variable set: {_k} -> {_v}")

            exec(exp)

    def _set_env_vars(self,env_vars=None,clobber=False):

        set_env_vars = env_vars

        if not set_env_vars:
            return

        for _k,_v in set_env_vars.items():

            if self.os_env_prefix in _k:
                _key = _k
            else:
                _key = _k.upper()

            if _v is None:
                continue

            if _key in os.environ and not clobber:
                continue

            if os.environ.get("JIFFY_ENHANCED_LOG"):
               print(f"o--o {_key} -> {_v}")

            os.environ[_key] = str(_v)

    def _set_os_env_prefix(self,**kwargs):

        if self.os_env_prefix: 
            return

        if self.app_name == "terraform":
            self.os_env_prefix = "TF_VAR"
        elif self.app_name == "ansible":
            self.os_env_prefix = "ANS_VAR"

    def _get_template_vars(self,**kwargs):

        # if the app_template_vars is provided, we use it, otherwise, we
        # assume it is the <APP_NAME>_EXEC_TEMPLATE_VARS
        _template_vars = kwargs.get("app_template_vars")

        if not _template_vars and self.app_name:
            _template_vars = "{}_EXEC_TEMPLATE_VARS".format(self.app_name)

        if not os.environ.get(_template_vars.upper()): 
            _template_vars = "ED_EXEC_TEMPLATE_VARS"

        if os.environ.get(_template_vars.upper()):
            return [ _var.strip() for _var in os.environ.get(_template_vars.upper()).split(",") ]

        if not self.os_env_prefix: 
            return

        # get template_vars e.g. "ANS_VAR_<var>"
        _template_vars = []

        for _var in os.environ.keys():
            if self.os_env_prefix not in _var: 
                continue

            self.logger.debug("{} found in {}".format(self.os_env_prefix,
                                                      _var))

            self.logger.debug("templating variable {}".format(_var))

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

        if self.docker_image:
            return

        if self.docker_runtime:
            self.docker_image = self.docker_runtime
            self.syncvars.class_vars["docker_image"] = self.docker_image
            return

        if self.docker_exec_env:
            self.docker_image = self.docker_exec_env
            self.syncvars.class_vars["docker_image"] = self.docker_image
            return 

        if not self.app_name:
            return 

        # docker image noet set but app_name is set
        self.docker_image = "elasticdev/{}-run-env".format(self.app_name)
        self.syncvars.class_vars["docker_image"] = self.docker_image

    def _mkdir(self,dir_path):

        if os.path.exists(dir_path): 
            return

        cmd = "mkdir -p {}".format(dir_path)

        self.execute(cmd,
                     output_to_json=False,
                     exit_error=True)

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

    def _set_app_params(self,**kwargs):

        if not self.app_name:
            return

        # app_name is set at this point

        # set app_dir
        if not self.app_dir:
            self.app_dir = os.environ.get("{}_DIR".format(self.app_name.upper()))

        if not self.app_dir:
            self.app_dir = "var/tmp/{}".format(self.app_name)

        if self.app_dir[0] == "/": 
            self.app_dir = self.app_dir[1:]

        # this can be overided by inherited class
        if not self.shelloutconfig:
            self.shelloutconfig = "config0-publish:::{}::resource_wrapper".format(self.app_name)

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

        if hasattr(self,"exec_dir") and self.exec_dir:

            self.template_dir = "{}/_config0_templates".format(self.exec_dir)

            # ref 34532045732
            self.resources_dir = os.path.join(self.exec_dir,
                                              "config0_resources")  

    def _get_resource_files(self):

        self.logger.debug("getting json files from resources_dir {}".format(self.resources_dir))

        if not os.path.exists(self.resources_dir): 
            self.logger.debug("DOES NOT EXIST resources_dir {}".format(self.resources_dir))
            return

        _files = glob.glob("{}/*.json".format(self.resources_dir))

        self.logger.debug(_files)

        if not _files: 
            return
        
        resources = []

        for _file in _files:

            try:
                _values = json.loads(open(_file,"r").read())
                resources.append(_values)
            except:
                self.logger.warn("could not retrieve resource json contents from {}".format(_file))

        if not resources: 
            return 

        if len(resources) == 1: 
            return resources[0]

        return resources

    def get_os_env_prefix_envs(self,remove_os_environ=True):

        '''
        get os env prefix vars e.g. TF_VAR_ipadddress and return
        the variables as lowercase withoout the prefix
        e.g. ipaddress
        '''

        if not self.os_env_prefix:
            return {}

        _split_key = "{}_".format(self.os_env_prefix)
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
            _env_keys = [ _key for _key in os.environ.keys() if self.os_env_prefix in _key ]
        except:
            _env_keys = None

        self.logger.debug_highlight('app_env_keys "{}" for os_env_prefix "{}"'.format(_env_keys,
                                                                                      self.os_env_prefix))

        return _env_keys

    def insert_os_env_prefix_envs(self,env_vars,exclude_vars=None):

        _env_keys = self.get_app_env_keys()

        if not _env_keys: 
            return

        if not exclude_vars:
            exclude_vars = []

        _split_key = "{}_".format(self.os_env_prefix)

        for _env_key in _env_keys:

            _var = _env_key.split(_split_key)[1].lower()

            if _var in exclude_vars: 
                self.logger.debug("insert_os_env_prefix_envs - skipping {}".format(_env_key))
                continue

            _env_value = os.environ.get(_env_key)

            if not _env_key: 
                continue

            if _env_value in [ "False", "false", "null", False]: 
                _env_value = "false"

            if _env_value in [ "True", "true", True]: 
                _env_value = "true"

            env_vars[_env_key] = _env_value

    def append_log(self,log):

        append = True

        if os.environ.get("JIFFY_LOG_FILE"):
            logfile = os.environ["JIFFY_LOG_FILE"]
        elif os.environ.get("CONFIG0_LOG_FILE"):
            logfile = os.environ["CONFIG0_LOG_FILE"]
        elif os.environ.get("LOG_FILE"):
            logfile = os.environ["LOG_FILE"]
        else:
            logfile = "/tmp/{}.log".format(self.stateful_id)
            append = False

        if eval_str_to_join(log):
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
                file.write("# append log ")
                file.write("#"*32)
                file.write(output)
                file.write("#"*32)
        else:
            with open(logfile, "w") as file:
                file.write("#"*32)
                file.write("# append log ")
                file.write("#"*32)
                file.write(output)
                file.write("#"*32)

        return logfile

    def to_resource_db(self,resources):

        output = _to_json(resources)
        print('_config0_begin_output')
        print(output)
        print('_config0_end_output')

        return

    def get_state_info(self):

        if not self.postscript_path:
            self.logger.warn("post script is not set")
            return

        if not os.path.exists(self.postscript_path):
            self.logger.warn("post script {} does not exists".format(self.postscript_path))
            return 

        os.chdir(self.exec_dir)
        cmd = [ self.postscript_path ]

        try:
            output = self.execute(cmd,
                                  output_to_json=False,
                                  exit_error=True).get("output")
        except:
            self.logger.debug("{} failed at dir {}".format(self.postscript_path,self.exec_dir))
            exit(9)

        # try to get resources from resource file 
        # in resources directory
        # ref 34532045732
        resources = self._get_resource_files()

        if resources: 
            return resources

        if not output: 
            return 

        # try to convert output with delimiters to values
        values = convert_config0_output_to_values(output)

        os.chdir(self.cwd)

        return values

    def add_mod_params(self,resource):
        self.logger.debug("add_mod_params is to specified by the inherited class")
        return

    def get_resource_details(self):

        resource = self.get_state_info()

        if not resource:
            return 

        return self.config_resource_details(resource)

    def config_resource_details(self,resource):

        resource = self._tfstate_to_output()

        if not isinstance(resource,dict) and not isinstance(resource,list):
            self.logger.error("resource needs to be a dictionary or list!")
            return False

        if isinstance(resource,dict):

            self.add_resource_tags(resource)

            try:
                self.add_mod_params(resource)
            except:
                self.logger.debug("Did not add destroy params")

        if isinstance(resource,list):

            for _resource in resource:

                self.add_resource_tags(_resource)

                if not _resource.get("main"):
                    continue

                try:
                    self.add_mod_params(_resource)
                except:
                    self.logger.debug("Did not add destroy params")

        return resource

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
    def get_env_var(self,variable,default=None,must_exists=None):

        _value = os.environ.get(variable)

        if _value:
            return _value

        if self.os_env_prefix:

            _value = os.environ.get("{}_{}".format(self.os_env_prefix,
                                                   variable))

            if _value:
                return _value

            _value = os.environ.get("{}_{}".format(self.os_env_prefix,
                                                   variable.lower()))

            if _value:
                return _value

            _value = os.environ.get("{}_{}".format(self.os_env_prefix,
                                                   variable.upper()))

            if _value:
                return _value

        if default:
            return default

        if not must_exists:
            return

        raise MissingEnvironmentVariable("{} does not exist".format(variable))

    def print_json(self,values):
        print_json(values)

    def templify(self,**kwargs):

        clobber = kwargs.get("clobber")
        _template_vars = self._get_template_vars(**kwargs)

        if not _template_vars:
            self.logger.debug_highlight("template vars is not set or empty")
            return

        self.logger.debug_highlight("template vars {} not set or empty".format(_template_vars))

        if not self.template_dir:
            self.logger.warn("template_dir not set (None) - skipping templating")
            return

        template_files = list_template_files(self.template_dir)

        if not template_files:
            self.logger.warn("template_files in directory {} empty - skipping templating".format(self.template_dir))
            return

        for _file_stats in template_files:

            template_filepath = _file_stats["file"]

            file_dir = os.path.join(self.exec_dir,
                                    _file_stats["directory"])

            file_path = os.path.join(self.exec_dir,
                                     _file_stats["directory"],
                                     _file_stats["filename"].split(".ja2")[0])

            if not os.path.exists(file_dir):
                os.system("mkdir -p {}".format(file_dir))

            if os.path.exists(file_path) and not clobber:
                self.logger.warn("destination templated file already exists at {} - skipping templifying of it".format(file_path))
                continue

            self.logger.debug("creating templated file file {} from {}".format(file_path,
                                                                               template_filepath))


            templateVars = {}

            if self.os_env_prefix:
                self.logger.debug("using os_env_prefix {}".format(self.os_env_prefix))
                _split_char = "{}_".format(self.os_env_prefix)
            else:
                _split_char = None

            if not _template_vars:
                self.logger.error("_template_vars is empty")
                exit(9)

            self.logger.debug("_template_vars {}".format(_template_vars))

            for _var in _template_vars:

                _value = None

                if self.os_env_prefix:

                    if self.os_env_prefix in _var:
                        _key = _var.split(_split_char)[1]
                        _value = os.environ.get(_var)
                    else:
                        _key = str("{}_{}".format(self.os_env_prefix,
                                                  _var))
                        _value = os.environ.get(_key)

                    if _value: _mapped_key = _key

                if not _value:
                    _value = os.environ.get(str(_var))
                    if _value: _mapped_key = _var

                if not _value:
                    _value = os.environ.get(str(_var.upper()))
                    if _value: _mapped_key = _var.upper()

                self.logger.debug("")
                self.logger.debug("mapped_key {}".format(_mapped_key))
                self.logger.debug("var {}".format(_var))
                self.logger.debug("value {}".format(_value))
                self.logger.debug("")

                if not _value: 
                    self.logger.warn("skipping templify var {}".format(_var))
                    continue

                value = _value.replace("'",'"')

                # include both uppercase and regular keys
                templateVars[_mapped_key] = value
                templateVars[_mapped_key.upper()] = value

            self.logger.debug("")
            self.logger.debug("templateVars {}".format(templateVars))
            self.logger.debug("")

            templateLoader = jinja2.FileSystemLoader(searchpath="/")
            templateEnv = jinja2.Environment(loader=templateLoader)
            template = templateEnv.get_template(template_filepath)
            outputText = template.render( templateVars )
            writefile = open(file_path,"w")
            writefile.write(outputText)
            writefile.close()

        return True

    def write_key_to_file(self,**kwargs):

        '''
        writing the value of a key in inputargs 
        into a file
        '''

        key = kwargs["key"]
        filepath = kwargs["filepath"]
        split_char = kwargs.get("split_char")
        add_return = kwargs.get("add_return",True)
        copy_to_share = kwargs.get("copy_to_share")
        deserialize = kwargs.get("deserialize")

        try:
            permission = str(int(kwargs.get("permission")))
        except:
            permission = "400"

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

        with open(filepath,"w") as wfile:

            for _line in _lines:
                # ref 45230598450
                #wfile.write(_line.replace('"','').replace("'",""))

                wfile.write(_line)

                if not add_return: 
                    continue

                wfile.write("\n")

        if permission: 
            os.system("chmod {} {}".format(permission,filepath))

        if copy_to_share: 
            self.copy_file_to_share(filepath)

        return filepath

    def copy_file_to_share(self,srcfile,dst_subdir=None):

        if not self.run_share_dir: 
            self.logger.debug("run_share_dir not defined - skipping sync-ing ...")
            return
            
        cmds = []
        _dirname = os.path.dirname(self.run_share_dir)

        if not os.path.exists(_dirname):
            cmds.append("mkdir -p {}".format(_dirname))

        _file_subpath = os.path.basename(srcfile)

        if dst_subdir:
            _file_subpath = "{}/{}".format(dst_subdir,_file_subpath)

        dstfile = "{}/{}".format(self.run_share_dir,_file_subpath)

        cmds.append("cp -rp {} {}".format(srcfile,dstfile))

        for cmd in cmds:
            self.execute(cmd,
                         output_to_json=False,
                         exit_error=True)

    def sync_to_share(self,rsync_args=None,exclude_existing=None):

        if not self.run_share_dir: 
            self.logger.debug("run_share_dir not defined - skipping sync-ing ...")
            return
            
        cmds = []
        _dirname = os.path.dirname(self.run_share_dir)

        if not os.path.exists(_dirname):
            cmds.append("mkdir -p {}".format(_dirname))

        if not rsync_args:
            rsync_args = "-avug"

        if exclude_existing:
            rsync_args = '{} --ignore-existing '.format(rsync_args)

        #rsync -h -v -r -P -t source target

        cmd = "rsync {} {}/ {}".format(rsync_args,
                                       self.exec_dir,
                                       self.run_share_dir)

        self.logger.debug(cmd)
        cmds.append(cmd)

        for cmd in cmds:
            self.execute(cmd,
                         output_to_json=False,
                         exit_error=True)

        self.logger.debug("Sync-ed to run share dir {}".format(self.run_share_dir))

    def remap_app_vars(self):

        if not self.os_env_prefix: 
            return

        _split_char = "{}_".format(self.os_env_prefix)

        _add_values = {}
        keys_to_delete = []

        for _key,_value in self.inputargs.items():

            if _split_char not in _key:
                continue

            _mapped_key = _key.split(_split_char)[-1]

            _add_values[_mapped_key] = _value
            keys_to_delete.append(_key)

            self.logger.debug("mapped key {} value {}".format(_key,
                                                              _value))

        for _mapped_key,_value in _add_values.items():
            self.inputargs[_mapped_key] = _value

        for key_to_delete in keys_to_delete:
            del self.inputargs[key_to_delete]

    def add_resource_tags(self,resource):

        tags = self.get_env_var("RESOURCE_TAGS")

        if not tags: 
            return

        if resource.get("tags"):
            return

        tags = [ tag.strip() for tag in tags.split(",") ]

        if not resource.get("tags"): 
            resource["tags"] = []

        resource["tags"].extend(tags)

        if self.app_name: 
            resource["tags"].append(self.app_name)

        # remove duplicates
        resource["tags"] = list(set(resource["tags"]))
 
        return resource

    def get_hash(self,_object):
        return get_hash(_object)

    def add_output(self,cmd=None,remove_empty=None,**results):

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

    def to_json(self,output):
        return _to_json(output)

    def print_output(self,**kwargs):

        output = _to_json(kwargs["output"])

        try:
            if isinstance(output,bytes):
                output = output.decode()
        except:
            print("could not convert output to string")

        try:
            if isinstance(output,str):
                output = output.split("\n")
        except:
            print("could not convert output to list")

        print('_config0_begin_output')

        if isinstance(output,list):
            for _output in output:
                print(_output)
        else:
            print(output)

    def jsonfile_to_phases_info(self):

        if not hasattr(self,"config0_phases_json_file"):
            self.logger.debug("jsonfile_to_phases_info - config0_phases_json_file not set")
            return

        if not self.config0_phases_json_file:
            return

        if not os.path.exists(self.config0_phases_json_file):
            return

        self.phases_info = get_values_frm_json(json_file=self.config0_phases_json_file)

    def delete_phases_to_json_file(self):

        if not hasattr(self,"config0_phases_json_file"):
            self.logger.debug("delete_phases_to_json_file - config0_phases_json_file not set")
            return

        if not self.config0_phases_json_file:
            return

        if not os.path.exists(self.config0_phases_json_file):
            return

        rm_rf(self.config0_phases_json_file)

    def write_phases_to_json_file(self,content_json):

        if not hasattr(self,"config0_phases_json_file"):
            self.logger.debug("write_phases_to_json_file - config0_phases_json_file not set")
            return

        if not self.config0_phases_json_file:
            return

        self.logger.debug(f"u4324: inserting retrieved data into {self.config0_phases_json_file}")

        to_jsonfile(content_json,
                    self.config0_phases_json_file)

    def write_resource_to_json_file(self,resource,must_exist=None):

        msg = "config0_resource_json_file needs to be set"

        if not hasattr(self,"config0_resource_json_file") or not self.config0_resource_json_file:
            if must_exist:
                raise Exception(msg)
            else:
                self.logger.debug(msg)
            return

        self.logger.debug(f"u4324: inserting retrieved data into {self.config0_resource_json_file}")

        to_jsonfile(resource,
                    self.config0_resource_json_file)
    def successful_output(self,**kwargs):
        self.print_output(**kwargs)
        exit(0)
        
    def clean_output(self,results,replace=True):

        clean_lines = []

        if isinstance(results["output"],list):
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

    def execute(self,cmd,**kwargs):

        results = self.execute3(cmd,**kwargs)

        return results

    def execute3(self,cmd,**kwargs):
        return execute3(cmd,**kwargs)

    def execute2(self,cmd,**kwargs):
        return execute3(cmd,**kwargs)

    def execute4(self,cmd,**kwargs):
        return execute4(cmd,**kwargs)

    def cmd_failed(self,**kwargs):
         
        failed_message = kwargs.get("failed_message")

        if not failed_message: 
            failed_message = "No failed message to outputted"

        self.logger.error(message=failed_message)
        exit(9)

    def _set_inputargs_to_false(self):

        for _k,_v in self.inputargs.items():

            if _v != "False": 
                continue

            self.inputargs[_k] = False

    def _add_to_inputargs(self,inputargs=None):

        if not inputargs:
            return

        for _k,_v in inputargs.items():

            if _k in self.inputargs:
                continue

            self.logger.debug(f"added to inputargs {_k} -> {_v}")
            self.inputargs[_k] = _v

    def set_inputargs(self,**kwargs):

        _inputargs = None

        if kwargs.get("inputargs"):
            _inputargs = kwargs["inputargs"]
            self._add_to_inputargs(_inputargs)

        elif kwargs.get("json_input"):
            _inputargs = to_json(kwargs["json_input"],
                                     exit_error=True)
            self._add_to_inputargs(_inputargs)

        if kwargs.get("add_app_vars") and self.os_env_prefix:
            _inputargs = self.get_os_env_prefix_envs(remove_os_environ=False)
            self._add_to_inputargs(_inputargs)

        if kwargs.get("set_env_vars"):
            _inputargs = self.parse_set_env_vars(kwargs["set_env_vars"])
            self._add_to_inputargs(_inputargs)

        standard_env_vars = [ "JOB_INSTANCE_ID",
                              "SCHEDULE_ID",
                              "RUN_ID",
                              "RESOURCE_TYPE",
                              "RESOURCE_TAGS",
                              "METHOD",
                              "PHASE" ]

        _inputargs = self.parse_set_env_vars(standard_env_vars)
        self._add_to_inputargs(_inputargs)
        self._set_inputargs_to_false()

    # This can be replaced by the inheriting class
    def parse_set_env_vars(self,env_vars):

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

    def check_required_inputargs(self,**kwargs):

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

        self.logger.aggmsg("These keys need to be set:",new=True)
        self.logger.aggmsg("")

        for key in required_keys:

            self.logger.aggmsg(f"\tkeys found include: {self.inputargs.keys()}")

            if self.os_env_prefix:
                self.logger.aggmsg("\t{} or Environmental Variable {}/{}_{}".format(key,
                                                                                    key.upper(),
                                                                                    self.os_env_prefix,
                                                                                    key))
            else:
                self.logger.aggmsg("\t{} or Environmental Variable {}".format(key,
                                                                              key.upper()))


        failed_message = self.logger.aggmsg("")
        self.cmd_failed(failed_message=failed_message)

    def check_either_inputargs(self,**kwargs):
      
        _keys = kwargs.get("keys")

        if not _keys: 
            return 

        for key in kwargs["keys"]:
            if key in self.inputargs: 
                return 

        self.logger.aggmsg("one of these keys need to be set:",new=True)
        self.logger.aggmsg("")

        for key in kwargs["keys"]:
            if self.os_env_prefix:
                self.logger.aggmsg("\t{} or Environmental Variable {}/{}_{}".format(key,
                                                                                    key.upper(),
                                                                                    self.os_env_prefix,
                                                                                    key))
            else:
                self.logger.aggmsg("\t{} or Environmental Variable {}".format(key,
                                                                              key.upper()))
        failed_message = self.logger.aggmsg("")
        self.cmd_failed(failed_message=failed_message)

    #######################################################################
    # testtest456 - move to resource_wrapper after testing
    # insert 45245
    #######################################################################

    def create(self):

        self.init_phase_run()

        if self.phase == "submit":
            self._init_create()
            self._exec_tf_apply()
        elif self.phase == "retrieve":
            self._exec_tf_apply()
        else:
            self._init_create()
            self._exec_tf_apply()

        self._eval_phases_tf("create")
        self._post_create()

        return

    def _insert_tf_version(self,env_vars):

        if env_vars.get("TF_VERSION"):
            return

        if os.environ.get("TF_VERSION"):
            env_vars["TF_VERSION"] = os.environ["TF_VERSION"]

        if hasattr(self,"tf_version") and self.tf_version:
            env_vars["TF_VERSION"] = self.tf_version
            return

        try:
            tf_version = self.docker_image.split(":")[-1]
        except:
            tf_version = None

        if not tf_version:
            try:
                tf_version = env_vars["DOCKER_IMAGE"].split(":")[-1]
            except:
                tf_version = "1.5.4"

        env_vars["TF_VERSION"] = tf_version

    def _set_build_method(self):

        if os.environ.get("USE_CODEBUILD"):  # longer than 900 seconds
            self.build_method = "codebuild"
        elif os.environ.get("USE_LAMBDA"):  # shorter than 900 seconds
            self.build_method = "lambda"
        elif os.environ.get("USE_AWS",True):  # select codebuild or lambda
            if int(self.build_timeout) > 600:
                self.build_method = "codebuild"
            else:
                self.build_method = "lambda"
        else:
            self.build_method = "local"

    def _get_tfstate_file(self):
        """
        This method gets the Terraform state file.
        """

        #bucket = "{self.remote_stateful_bucket}"
        #key = "{self.stateful_id}.tfstate"

        if os.path.exists(self.tf_exec_state_file):
            tfstate_file = self.tf_exec_state_file

            with open(tfstate_file) as json_file:
                data = json.load(json_file)

        else:
            cmd = f'aws s3 cp s3://{self.remote_stateful_bucket}/{self.stateful_id}.tfstate /tmp/{self.stateful_id}.tfstate'

            self.execute(cmd,
                         output_to_json=False,
                         exit_error=True)

            tfstate_file = f"/tmp/{self.stateful_id}.tfstate"

            # read output file
            with open(tfstate_file) as json_file:
                data = json.load(json_file)

            os.system(f'rm -rf {tfstate_file}')

        if not data:
            msg = "tfstate_to_output: there is no data from {}".format(os.path.join(os.getcwd(),
                                                                                    self.tf_exec_state_file))
            self.logger.debug(msg)
            return

        return data

    def add_mod_params(self,resource):

        '''
        - we typically load the modifications parameters along with created resource like a
        VPC or database

        - the resource is therefore self contained, whereby it specifies to the
        system how it can be validated/destroyed.

        - for terraform, we include things like the docker image used to
        validate/destroy the resource and any environmental variables
        '''

        # Create mod params resource arguments and reference
        resource["mod_params"] = {"shelloutconfig":self.shelloutconfig}

        # environmental variables to include during destruction
        env_vars = {
            "DOCKER_EXEC_ENV": self.docker_image,
            "DOCKER_RUNTIME": self.docker_image,
            "REMOTE_STATEFUL_BUCKET":self.remote_stateful_bucket,
            "STATEFUL_ID": self.stateful_id,
            "BUILD_TIMEOUT": self.build_timeout,
            "APP_DIR":self.app_dir,
        }

        self._insert_tf_version(env_vars)

        if hasattr(self,"drift_protection") and self.drift_protection:
            resource["drift_protection"] = self.drift_protection

        resource["mod_params"]["env_vars"] = env_vars

        if env_vars.get("STATEFUL_ID"):
            resource["mod_params"]["stateful_id"] = env_vars["STATEFUL_ID"]

        if self.mod_execgroup:
            resource["mod_params"]["execgroup"] = self.mod_execgroup

        if self.destroy_env_vars:
            resource["destroy_params"] = {
                "env_vars": dict({"METHOD": "destroy"},
                                 **self.destroy_env_vars)
            }
        else:
            resource["destroy_params"] = {
                "env_vars": {"METHOD": "destroy"}
            }

        if self.validate_env_vars:
            resource["validate_params"] = {
                "env_vars":dict({"METHOD":"validate"},
                                **self.validate_env_vars)
            }
        else:
            resource["validate_params"] = {
                "env_vars":{"METHOD":"validate"}
            }

        return resource

    def _eval_phases_tf(self,method):

        # add feature
        # can add failure count in the future

        try:
            build_expire_at = self.tf_results["inputargs"]["build_expire_at"]
        except:
            build_expire_at = None

        # this is implemented in phases
        if self.phases_params_hash or self.phases_params:
            if self.phases_params_hash:
                json_values = {
                        "results":self.tf_results,
                        "status":self.tf_results.get("status"),
                        "phases_params_hash":self.phases_params_hash
                    }
            elif self.phases_params:
                json_values = {
                        "results":self.tf_results,
                        "status":self.tf_results.get("status"),
                        "phases_params_hash":b64_encode(self.phases_params),
                    }

            if build_expire_at:
                json_values["build_expire_at"] = build_expire_at

            self.write_phases_to_json_file(json_values)

        return True

    def _eval_failure(self,method=None):

        output = None

        if not hasattr(self,"tf_results"):
            return

        if not self.tf_results:
            return

        if self.tf_results.get("output"):
            output = self.tf_results["output"]
            del self.tf_results["output"]
            self.append_log(output)

        if output:
            print(output)

        if self.tf_results.get("status") is False:
            # failed at this point
            if self.tf_results.get("failed_message"):
                failed_message = self.tf_results.get("failed_message")
            else:
                failed_message = f"Terraform apply {method} failed here {self.run_share_dir}!"

            # this should also be removed further upstream
            # but included to be explicit
            self.delete_phases_to_json_file()

            # self.logger.error(failed_message)
            raise Exception(failed_message)

        return True

    def _get_next_phase(self,method="create",**json_info):

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

        os.system(f"rm -rf {self.run_share_dir}")

        self.logger.error("Cannot determine next phase to run - reset")
        raise Exception("Cannot determine next phase to run")

    def set_cur_phase(self):

        '''
        self.phases_params_hash = None
        self.phases_params = None
        self.phases_info = None
        self.phase = None  # can be "run" since will only one phase
        self.current_phase None
        '''

        self.jsonfile_to_phases_info()

        if self.phases_info and self.phases_info.get("inputargs"):
            self.set_class_vars(self.phases_info["inputargs"])

        if self.phases_info and self.phases_info.get("phases_params_hash"):
            self.phases_params_hash = self.phases_info["phases_params_hash"]
        else:
            self.phases_params_hash = os.environ.get("PHASES_PARAMS_HASH")

        if not self.phases_info and not self.phases_params_hash:
            self.logger.debug("Phase are not implemented")
            return

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

    #################################

    def _get_aws_exec_cinputargs(self,method="create"):

        cinputargs = {
            "method":method,
            "build_timeout":self.build_timeout,
            "run_share_dir":self.run_share_dir,
            "app_dir":self.app_dir,
            "remote_stateful_bucket":self.remote_stateful_bucket,
            "aws_region":self.aws_region
        }

        if self.build_env_vars:
            cinputargs["build_env_vars"] = self.build_env_vars

        if self.ssm_name:
            cinputargs["ssm_name"] = self.ssm_name

        if self.phases_info:
            cinputargs["phases_info"] = self.phases_info

        return cinputargs

    def _exec_codebuild(self,method="create"):

        cinputargs = self._get_aws_exec_cinputargs(method=method)
        _awsbuild = Codebuild(**cinputargs)

        if self.phase == "retrieve":
            return _awsbuild.retrieve(**self.get_phase_inputargs())

        # submit and run required env file
        self.create_build_envfile()

        if self.phase == "submit":
            return _awsbuild.submit(**self.get_phase_inputargs())

        return _awsbuild.run()

    def _exec_lambdabuild(self,method="create"):

        cinputargs = self._get_aws_exec_cinputargs(method=method)
        _awsbuild = Lambdabuild(**cinputargs)

        #if self.phase == "retrieve":
        #    return _awsbuild.retrieve(**self.get_phase_inputargs())

        # submit and run required env file
        if method == "create":
            self.create_build_envfile(openssl=False)

        #if self.phase == "submit":
        #    return _awsbuild.submit(**self.get_phase_inputargs())
        results = _awsbuild.run()

        return results

    def create_config0_settings_file(self):

        try:
            value = os.environ.get("CONFIG0_RESOURCE_SETTINGS_HASH")
        except:
            value = None

        if not value:
            return

        _file = os.path.join(
            self.run_share_dir,
            self.app_dir,
            "config0_resource_settings_hash")

        with open(_file, "w") as file:
            file.write(value)

    def create_remote_tf_bkend(self):

        _file = os.path.join(
            self.run_share_dir,
            self.app_dir,
            "backend.tf"
        )

        contents = f"""\
terraform {{
  backend "s3" {{
    bucket = "{self.remote_stateful_bucket}"
    key    = "{self.stateful_id}.tfstate"
    region = "{self.aws_region}"
  }}
}}

"""

        with open(_file, "w") as file:
            file.write(contents)

    def create_build_envfile(self,openssl=True):
        '''
        we use stateful_id for the encrypt key
        '''

        if not self.build_env_vars:
            return

        envfile = os.path.join(self.run_share_dir,
                               self.app_dir,
                               "build_env_vars.env")

        if self.build_env_vars.get("STATEFUL_ID"):
            create_envfile(self.build_env_vars,
                           envfile=f"{envfile}.enc",
                           secret=self.build_env_vars["STATEFUL_ID"],
                           openssl=openssl)
        else:
            create_envfile(self.build_env_vars,
                           envfile=envfile)

        return True

    def _exec_tf(self,method):

        if self.build_method == "codebuild":
            self.tf_results = self._exec_codebuild(method=method)
        elif self.build_method == "lambda":
            self.tf_results = self._exec_lambdabuild(method=method)
        else:  # execute locally
            self._create_docker_env_file()
            self.tf_results = self._exec_docker_local(method=method)

        print_json(self.tf_results)
        raise Exception("dsfasfd")

        return self.tf_results

    def _exec_tf_validate(self):

        self._get_runtime_env_vars(method="validate")
        self._set_build_method()
        self._exec_tf(method="validate")

        return self.tf_results

    def _exec_tf_destroy(self):

        self._get_runtime_env_vars(method="destroy")
        self._set_build_method()
        self._exec_tf(method="destroy")

        return self.tf_results

    def validate(self):
        self._exec_tf_validate()
        return self._eval_failure(method="validate")

    def destroy(self):

        self.init_phase_run()

        if self.phase == "submit":
            self._exec_tf_destroy()
        elif self.phase == "retrieve":
            self._exec_tf_destroy()
        else:
            self._exec_tf_destroy()

        self._eval_phases_tf("destroy") # see if phases

        try:
            os.chdir(self.cwd)
        except:
            os.chdir("/tmp")

        return self._eval_failure(method="destroy")