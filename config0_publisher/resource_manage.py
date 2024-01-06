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
#Written by Gary Leong  <gary@config0.com, May 11,2022

import os
import jinja2
import glob
import json
import boto3

from time import sleep

from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import print_json
from config0_publisher.utilities import to_json
from config0_publisher.utilities import get_values_frm_json
from config0_publisher.utilities import get_hash
from config0_publisher.shellouts import execute4
from config0_publisher.shellouts import execute3
#from config0_publisher.shellouts import execute3a

from config0_publisher.serialization import b64_decode
from config0_publisher.serialization import b64_encode
from config0_publisher.variables import SyncClassVarsHelper
from config0_publisher.templating import list_template_files
from config0_publisher.output import convert_config0_output_to_values

#import sys
#reload(sys)
#sys.setdefaultencoding('utf8')

# ref 34532045732
def to_jsonfile(values,filename,exec_dir=None):

    if not exec_dir: 
        exec_dir = os.getcwd()

    file_dir = os.path.join(exec_dir,
                            "config0_resources")

    file_path = os.path.join(file_dir,
                             filename)

    if not os.path.exists(file_dir):
        os.system("mkdir -p {}".format(file_dir))

    try:
        with open(file_path,"w") as f:
            f.write(json.dumps(values))
        status = True
        print("Successfully wrote contents to {}".format(file_path))
    except:
        print("Failed to write contents to {}".format(file_path))
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

        self.phases_params_hash = None
        self.phases_params = None
        self.phases_info = None
        self.phase = None  # can be "run" since will only one phase
        self.current_phase = None

        ###############################################
        # testtest456
        ###############################################

        os.environ["USE_CODEBUILD"] = "True"  # longer than 900 seconds

        self.phases_params = [
                  {
                      "name": "submit",
                      "timewait": None,
                  },
                  {
                      "name": "retrieve",
                      "timewait": 30,
                      "inputargs": {
                          "interval": 10,
                          "retries": 12
                      }
                  }
        ]

        self.phases_params_hash = b64_encode(self.phases_params)
        ###############################################

        # set specified env variables
        self._set_env_vars(**kwargs)
        self._set_os_env_prefix(**kwargs)
        self._set_app_params(**kwargs)
        
        self._init_syncvars(**kwargs)
        self._set_class_vars()
        self._finalize_set_vars()

    def init_phase_run(self):
        # testtest456
        self.logger.debug("0"*32)
        self.logger.debug(self.phase)
        self.logger.debug("1"*32)
        self.logger.json(self.current_phase)
        self.logger.debug("2"*32)

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

        self._set_destroy_env_vars()
        self._get_docker_env_filepath()

        # special keywords for chrootfiles_dest_dir 
        self._set_special_keywords_classvars()

        self._set_class_vars()  # execute it final time to synchronize class vars set

        self.syncvars.set(init=None)
        self._set_env_vars(env_vars=self.syncvars.class_vars)  # synchronize to env variables

        self.config0_resource_json = os.environ.get("CONFIG0_RESOURCE_JSON_FILE")
        self.logger.debug('u4324: CONFIG0_RESOURCE_JSON_FILE "{}"'.format(self.config0_resource_json))

        self.config0_phases_json = os.environ.get("CONFIG0_PHASES_JSON_FILE")
        self.logger.debug('u4324: CONFIG0_PHASES_JSON_FILE "{}"'.format(self.config0_phases_json))

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            try:
                self._print_out_key_class_vars()
            except:
                self.logger.debug("could not print out debug class vars")

    def _print_out_key_class_vars(self):

        for _k,_v in self.syncvars.class_vars.items():
            try:
                self.logger.debug("{} -> {}".format(_k,_v))
            except:
                self.logger.warn("could not print class vars {}".format(_k))

    def _set_special_keywords_classvars(self):

        chrootfiles_dest_dir = self.syncvars.class_vars.get("chrootfiles_dest_dir")
        working_dir = self.syncvars.class_vars.get("working_dir")
        run_share_dir = self.syncvars.class_vars.get("run_share_dir")

        keys = [ "chrootfiles_dest_dir", "working_dir" ]

        for key in keys:

            if not self.syncvars.class_vars.get(key):
                continue

            value = self.syncvars.class_vars[key]

            if value not in ["_set_to_run_share_dir", "_set_to_share_dir"]:
                continue

            if not run_share_dir:
                self.logger.warn(f"could not set {key} run_share_dir")
                self.syncvars.class_vars[key] = None
                exp = 'self.{}=None'.format(key)
                exec(exp)
            else:
                self.syncvars.class_vars[key] = run_share_dir

    def _init_syncvars(self,**kwargs):

        inputargs = kwargs.get("inputargs")
        set_variables = kwargs.get("set_variables")
        set_must_exists = kwargs.get("set_must_exists")
        set_non_nullable = kwargs.get("set_non_nullable")
        set_default_values = kwargs.get("set_default_values")

        must_exists = ["stateful_id"]
        non_nullable = []

        #non_nullable = ["stateful_id"]
        
        variables = [ "stateful_id",
                      "chrootfiles_dest_dir",
                      "working_dir",
                      "stateful_dir",
                      "exec_base_dir",
                      "tmp_bucket",
                      "log_bucket",
                      "run_share_dir",
                      "remote_stateful_bucket",
                      "tmpdir",
                      "share_dir",
                      "docker_runtime",
                      "docker_exec_env",
                      "docker_image",
                      "destroy_execgroup",
                      "destroy_env_vars" ]

        default_values = { "share_dir":"/var/tmp/share",
                           "run_share_dir":None,
                           "tmp_bucket":None,
                           "log_bucket":None,
                           "stateful_id":None,
                           "destroy_env_vars":None,
                           "destroy_execgroup":None,
                           "docker_runtime":None,
                           "docker_exec_env":None,
                           "docker_image":None,
                           "tmpdir":"/tmp",
                           "exec_base_dir":os.getcwd() }

        if set_must_exists:
            must_exists.extend(set_must_exists)

        if set_non_nullable:
            non_nullable.extend(set_non_nullable)

        if set_variables:
            variables.extend(set_variables)

        if set_default_values:
            default_values.update(set_default_values)

        self.syncvars = SyncClassVarsHelper(os_env_prefix=self.os_env_prefix,
                                            app_name=self.app_name,
                                            app_dir=self.app_dir,
                                            variables=variables,
                                            must_exists=must_exists,
                                            non_nullable=non_nullable,
                                            inputargs=inputargs,
                                            default_values=default_values)

        self.syncvars.set(init=True)

    def _set_class_vars(self):

        for _k,_v in self.syncvars.class_vars.items():
            if _v is None:
                exp = "self.{}=None".format(_k)
            elif _v is False:
                exp = "self.{}=False".format(_k)
            elif _v is True:
                exp = "self.{}=True".format(_k)
            else:
                exp = 'self.{}="{}"'.format(_k,_v)

            exec(exp)

    def _set_env_vars(self,**kwargs):

        set_env_vars = kwargs.get("env_vars")

        if not set_env_vars:
            return

        for _k,_v in set_env_vars.items():
            if _v is None:
                continue
            os.environ[_k] = str(_v)
            if os.environ.get("JIFFY_ENHANCED_LOG"):
               print(f"{_k} -> {_v}")

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

    def _set_destroy_env_vars(self):

        if not self.destroy_env_vars:
            return

        try:
            self.destroy_env_vars = eval(self.destroy_env_vars)
        except:
            self.destroy_env_vars = None

        self.syncvars.class_vars["destroy_env_vars"] = self.destroy_env_vars

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

        try:
            _str = "\n".join(log)
        except:
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

        #if append:
            #self.logger.debug("#"*32)
            #self.logger.debug("# append logfile")
            #self.logger.debug(f"# {logfile}")
            #self.logger.debug("#"*32)
            #self.logger.debug(output)
            #self.logger.debug("#"*32)
        #else:
            #self.logger.debug("#"*32)
            #self.logger.debug("# write logfile")
            #self.logger.debug(f"# {logfile}")
            #self.logger.debug("#"*32)
            #self.logger.debug(output)
            #self.logger.debug("#"*32)

        return logfile

    def to_resource_db(self,resources):

        #print('ui'*32)
        output = _to_json(resources)
        print('_config0_begin_output')
        print(output)
        print('_config0_end_output')
        #print('ui'*32)

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

    def add_destroy_params(self,resource):

        self.logger.debug("add_destroy_params is to specified by the inherited class")

        return 

    def get_resources_details(self):

        resources = self.get_state_info()

        if not resources: 
            return 

        return self.configure_resources_details(resources)

    def configure_resources_details(self,resources):

        if not isinstance(resources,dict) and not isinstance(resources,list):
            self.logger.error("resource needs to be a dictionary or list!")
            return False

        if isinstance(resources,dict): 

            self.add_resource_tags(resources)

            try:
                self.add_destroy_params(resources)
            except:
                self.logger.debug("Did not add destroy params")

        if isinstance(resources,list):

            for _resource in resources:

                self.add_resource_tags(_resource)

                if not _resource.get("main"): 
                    continue

                try:
                    self.add_destroy_params(_resource)
                except:
                    self.logger.debug("Did not add destroy params")

        return resources

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

        if not hasattr(self,"config0_phases_json"):
            self.logger.debug("write_phases_to_json_file - config0_phases_json not set")
            return

        if not self.config0_phases_json:
            return

        if not os.path.exists(self.config0_phases_json):
            return

        self.phases_info = get_values_frm_json(json_file=self.config0_phases_json)

    # testtest456
    def write_phases_to_json_file(self,content_json):

        if not hasattr(self,"config0_phases_json"):
            self.logger.debug("write_phases_to_json_file - config0_phases_json not set")
            return

        if not self.config0_phases_json:
            return

        self.logger.debug("u4324: inserting retrieved data into {}".format(self.config0_phases_json))

        to_jsonfile(content_json,
                    self.config0_phases_json)

    def write_resource_to_json_file(self,resource,must_exist=None):

        msg = "config0_resource_json needs to be set"

        if not hasattr(self,"config0_resource_json") or not self.config0_resource_json:
            if must_exist:
                raise Exception(msg)
            else:
                self.logger.debug(msg)
            return

        self.logger.debug("u4324: inserting retrieved data into {}".format(self.config0_resource_json))

        to_jsonfile(resource,
                    self.config0_resource_json)
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

            self.logger.aggmsg("\tkeys found include: {}".format(self.inputargs.keys()))

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
    #######################################################################

    def _get_next_phase(self,**json_info):

        results = json_info["results"]
        phases_params = b64_decode(json_info["phases_params_hash"])

        phase_names = [phase["name"] for phase in phases_params]

        completed = []

        for phase_info in results["phases"]["phases_info"]:
            if phase_info.get("status"):
                completed.append(phase_info["name"])

        for phase_param in phases_params:
            if phase_param["name"] in completed:
                continue

            self.logger.debug(f'Next {phase_param["name"]} to run')
            return phase_param

        raise Exception(f"No next phase to run")

    def set_cur_phase(self):

        '''
        self.phases_params_hash = None
        self.phases_params = None
        self.phases_info = None
        self.phase = None  # can be "run" since will only one phase
        self.current_phase None
        '''

        self.jsonfile_to_phases_info()

        # testtest456
        self.logger.debug("k1"*32)
        self.logger.json(self.phases_info)
        self.logger.debug("k2"*32)

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
            self.current_phase = self._get_next_phase(**self.phases_info)
        elif self.phases_params_hash:
            self.current_phase = self.phases_params[0]  # first phase

        self.phase = self.current_phase["name"]

        # testtest456
        self.logger.debug("a"*32)
        self.logger.debug(self.phases_params_hash)
        self.logger.debug("b"*32)
        self.logger.debug(self.phases_params)
        self.logger.debug("c"*32)
        self.logger.debug(self.phase)
        self.logger.debug("d"*32)
        self.logger.json(self.current_phase)
        self.logger.debug("e"*32)
        self.logger.debug("e"*32)
        self.logger.debug("e"*32)
        self.logger.debug("e"*32)

    #######################################################################
    #######################################################################
