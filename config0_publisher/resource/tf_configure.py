#!/usr/bin/env python
#

import os
import json
from ast import literal_eval

from config0_publisher.shellouts import execute3
from config0_publisher.serialization import b64_decode
from config0_publisher.serialization import decode_and_decompress_string
from config0_publisher.loggerly import Config0Logger
from config0_publisher.loggerly import nice_json
from config0_publisher.utilities import get_hash
###########################
from config0_publisher.serialization import b64_encode
from config0_publisher.resource.codebuild import Codebuild
from config0_publisher.resource.lambdabuild import Lambdabuild
###########################

#from config0_publisher.class_helper import dict_to_classobj

def get_tfstate_file_remote(remote_stateful_bucket,stateful_id):

    cmd = f'aws s3 cp s3://{remote_stateful_bucket}/{stateful_id}.tfstate /tmp/{stateful_id}.tfstate'

    data = None

    execute3(cmd,
             output_to_json=False,
             exit_error=True)

    tfstate_file = f"/tmp/{stateful_id}.tfstate"

    # read output file
    with open(tfstate_file) as json_file:
        data = json.load(json_file)

    os.system(f'rm -rf {tfstate_file}')

    return data

def get_tf_bool(value):

    bool_none = [ "None",
                  "none",
                  "null",
                  "NONE",
                  "None",
                  None ]

    bool_false = [ "false",
                   "False",
                   "FALSE",
                   False ]

    bool_true = [ "TRUE",
                  "true",
                  "True",
                  True ]

    if value in bool_none:
        return 'null'

    if value in bool_false:
        return 'false'

    if value in bool_true:
        return 'true'

    return value

def tf_map_list_fix_value(_value):

    # check object type
    # convert to string
    if isinstance(_value,dict):
        _value = json.dumps(_value)

    if isinstance(_value,list):
        _value = json.dumps(_value)

    # check if string object is a list or dict
    _map_list_prefixes = ["[","{"]
    _map_list_suffixes = ["]","}"]

    _status = None

    try:
        _first_char = _value[0]
    except:
        _first_char = None

    if not _first_char:
        msg = "cannot determine first character for _value {} type {}".format(_value,
                                                                              type(_value))

        raise Exception(msg)

    if _value[0] not in _map_list_prefixes:
        return _value,_status

    # map or list?
    _status = True
    _value = _value.replace("'",'"')

    if _value[0] not in _map_list_prefixes and _value[0] in ["'",'"']:
        msg = "the first character should be {}".format(_map_list_prefixes)
        raise Exception(msg)

    if _value[-1] not in _map_list_suffixes and _value[-1] in ["'",'"']:
        msg = "the last character should be {}".format(_map_list_suffixes)
        raise Exception(msg)

    return _value,_status

def tf_number_value(value):

    try:
        value0 = value[0]
    except:
        value0 = None

    if value0 and value0 in [ "0", 0 ]:
        return 0,False

    if "." in str(value):

        try:
            eval_value = float(value)
            value_type = "float"
        except:
            eval_value = value
            value_type = None
    else:

        try:
            eval_value = int(value)
            value_type = "int"
        except:
            eval_value = value
            value_type = None

    return eval_value,value_type

def tf_iter_to_str(obj):

    if isinstance(obj,list) or isinstance(obj,dict):
        try:
            new_obj = json.dumps(literal_eval(json.dumps(obj)))
        except:
            new_obj = json.dumps(obj).replace("'",'"')

        return new_obj

    try:
        new_obj = json.dumps(literal_eval(obj))
    except:
        new_obj = obj

    return new_obj

class Config0SettingsEnvVarHelper:

    def __init__(self,**kwargs):

        self.classname = "Config0SettingsEnvVarHelper"

        self.logger = Config0Logger(self.classname,
                                    logcategory="cloudprovider")

        self.CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH = kwargs.get("CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH")
        self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH = kwargs.get("CONFIG0_RESOURCE_EXEC_SETTINGS_HASH")

        self._vars = {
            "runtime_env_vars":{},
            "exclude_tfvars":[],
            "build_env_vars":{}
        }

    def _set_frm_config0_resource_settings(self,raise_on_error=True):

        """
        This method initializes the Config0 resource settings.
        """

        if self.CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH:
            CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH = self.CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH
        else:
            CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH = os.environ.get("CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH")

        if self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH:
            CONFIG0_RESOURCE_EXEC_SETTINGS_HASH = self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH
        else:
            CONFIG0_RESOURCE_EXEC_SETTINGS_HASH = os.environ.get("CONFIG0_RESOURCE_EXEC_SETTINGS_HASH")

        if CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH:
            try:
                _settings = decode_and_decompress_string(CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH)
            except:
                _settings = {}  # probably destroy
        elif CONFIG0_RESOURCE_EXEC_SETTINGS_HASH:
            try:
                _settings = b64_decode(CONFIG0_RESOURCE_EXEC_SETTINGS_HASH)
            except:
                _settings = {}  # probably destroy
        else:
            _settings = {}

        if not _settings:
            failed_message = "The settings is empty for CONFIG0_RESOURCE_EXEC_SETTINGS_HASH"
            if raise_on_error:
                raise Exception(failed_message)
            self.logger.error(failed_message)
            return

        resource_runtime_settings_hash = _settings.get("resource_runtime_settings_hash")
        tf_runtime_settings_hash = _settings.get("tf_runtime_settings_hash")

        if resource_runtime_settings_hash:
            resource_runtime_settings = b64_decode(resource_runtime_settings_hash)

            self._vars["provider"] = resource_runtime_settings.get("provider")
            self._vars["resource_type"] = resource_runtime_settings.get("type")
            self._vars["resource_values"] = resource_runtime_settings.get("values")
            self._vars["resource_labels"] = resource_runtime_settings.get("labels")

        if tf_runtime_settings_hash:
            os.environ["TF_RUNTIME_SETTINGS"] = tf_runtime_settings_hash
            tf_runtime_settings = b64_decode(tf_runtime_settings_hash)

            self._vars["tf_configs"] = tf_runtime_settings["tf_configs"]
            self._vars["tf_runtime_env_vars"] = tf_runtime_settings.get("env_vars")  # ref 4532643623642
            self._vars["terraform_type"] = self._vars["tf_configs"].get("terraform_type")

    def _set_tf_runtime(self):

        tf_runtime = self._vars["tf_configs"].get("tf_runtime")

        if tf_runtime:
            self.logger.debug(f'tf_runtime {tf_runtime} from "tf_configs"')
            self._vars["tf_runtime"] = tf_runtime
            return tf_runtime

        tf_runtime = os.environ.get("TF_RUNTIME")

        if tf_runtime:
            self.logger.debug(f'tf_runtime {tf_runtime} from env var "TF_RUNTIME"')
        else:
            tf_runtime = "tofu:1.6.2"
            self.logger.debug(f'using default tf_runtime "{tf_runtime}"')

        self._vars["tf_runtime"] = tf_runtime

        return tf_runtime

    def _set_tf_binary_version(self):

        try:
            self._vars["binary"],self._vars["version"] = self._vars["tf_runtime"].split(":")
        except:
            self.logger.debug(f'could not evaluate tf_runtime - using default {self._vars["tf_runtime"]}"')
            self._vars["binary"] = "tofu"
            self._vars["version"] = "1.6.2"

        return self._vars["binary"],self._vars["version"]

    def eval_config0_resource_settings(self,create=None):

        self._set_frm_config0_resource_settings()

        # if it is creating for the first time
        if create:

            if not self._vars.get("resource_type"):
                raise Exception("resource_type needs to be set")

            if not self._vars.get("terraform_type"):
                raise Exception("terraform_type needs to be set")

        if not self._vars.get("provider"):
            self.logger.error("provider should be set")

        self._set_tf_runtime()
        self._set_tf_binary_version()

        for k,v in self._vars.items():
            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug(f'{k} -> {nice_json(v)}')
            setattr(self,k,v)

# init and reconfigure (update)
class ConfigureTFforConfig0Db(Config0SettingsEnvVarHelper):

    def __init__(self,db_values):

        '''
        self.get_hash => import get_hash
        self.tfstate_values => _get_tfstate_file_remote()_

        self.remote_stateful_bucket = values["remote_stateful_bucket"]
        self.stateful_id = values["stateful_id"]
        self.terraform_type = values["terraform_type"]

        self.tf_exec_skip_keys = values["last_applied"]["tf"]["exec"]["skip_keys"]
        self.tf_exec_add_keys = values["last_applied"]["tf"]["exec"]["add_keys"]
        self.tf_exec_map_keys = values["last_applied"]["tf"]["exec"]["map_keys"] = self.tf_exec_map_keys
        self.tf_exec_remove_keys = values["last_applied"]["tf"]["exec"]["remove_keys"]
        '''

        self.classname = "Config0ResourceTFVars"

        self.std_labels_keys = [
            "region",
            "provider",
            "source_method",
            "resource_type",
        ]

        self.tf_exec_skip_keys = [
            "sensitive_attributes",
            "ses_smtp_password_v4",
        ]

        self.do_not_display = [
            "AWS_SECRET_ACCESS_KEY",
            "secret",
        ]

        self.tf_output_skip_keys = [
            "tags",
            "label",
            "tag",
            "_id",
            "resource_type",
            "provider",
            "labels",
        ]

        self.tf_exec_add_keys = []

        self.tf_exec_remove_keys = [
            "private",
            "secret",
        ]

        self.tf_exec_map_keys = {}
        self.tfstate_values = {}

        self._db_values = db_values
        self._last_applied_add_keys = []
        self._db_removed_values = {}

        if not self._db_values:
            failed_message = "db_values cannot be empty for configuration for config0 db"
            raise Exception(failed_message)

        Config0SettingsEnvVarHelper.__init__(self,
                                             CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH=self._db_values.get("CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH"),
                                             CONFIG0_RESOURCE_EXEC_SETTINGS_HASH=self._db_values.get("CONFIG0_RESOURCE_EXEC_SETTINGS_HASH"))

    def _setup_for_configuration(self):

        self.eval_config0_resource_settings()
        self._set_parse_settings_for_tfstate()

        # this is probably for configuring if values are provided
        # testtest456
        self.remote_stateful_bucket = self._db_values["remote_stateful_bucket"]
        self.stateful_id = self._db_values["stateful_id"]
        self.terraform_type = self._db_values["terraform_type"]

        try:
            self._last_applied_add_keys = self._db_values["last_applied"]["tf"]["exec"]["add_keys"]
        except:
            self._last_applied_add_keys = []

        # testtest456
        # revisit 324214
        # should we compress this?
        self.tfstate_values = b64_decode(self._db_values["raw"]["terraform"])

    def _insert_tf_map_keys(self):

        self.logger.debug("#" * 32)
        self.logger.debug("insert_frm_tfstate_to_values: tf_exec_map_keys")
        self.logger.json(self.tf_exec_map_keys)
        self.logger.debug("#" * 32)

        if not self.tf_exec_map_keys:
            return

        self._db_values["last_applied"]["tf"]["exec"]["map_keys"] = self.tf_exec_map_keys

        for _insertkey,_refkey in self.tf_exec_map_keys.items():

            '''
            # _insertkey = "p1"
            # _refkey = "q1"

            # _insertkey = values
            # _refkey = {"a":"b","c":"d"}
            # values["values"]["a"] = values["b"]
            '''

            if self._db_values.get(_insertkey):
                self.logger.warn(f"mapped key {_insertkey} already exists - clobbering")

            # see if _refkey is a subkey
            if isinstance(_refkey,dict):

                if not self._db_values.get(_insertkey):
                    self._db_values[_insertkey] = {}

                self._db_values["last_applied"]["tf"]["added"].append(_insertkey)

                for _sub_insertkey,_sub_refkey in _refkey.items():

                    if not self._db_values.get(_sub_refkey):
                        self.logger.debug(
                            f'mapped ref_key not found {_sub_refkey} for sub_insertkey {_sub_insertkey}')
                    # ref 432523543245
                    # do we want to nest 2 levels deep?
                    if "," in self._db_values[_sub_refkey]:
                        _sub_insertkey2,_subrefkey2 = self._db_values[_sub_refkey].split(",")

                        if _sub_insertkey2 not in self.do_not_display:
                            self.logger.debug('mapped key ["{}"]["{}"]["{}"] -> _sub_refky "{}"'.format(_insertkey,
                                                                                                        _sub_insertkey,
                                                                                                        _sub_insertkey2,
                                                                                                        self._db_values[_sub_refkey.strip()][_subrefkey2.strip()]))

                        self._db_values[_insertkey][_sub_insertkey] = self._db_values[_sub_refkey.strip()][_subrefkey2.strip()]

                    else:
                        if _sub_insertkey not in self.do_not_display:
                            self.logger.debug('mapped key ["{}"]["{}"] -> _sub_refkey "{}"'.format(_insertkey,
                                                                                                   _sub_insertkey,
                                                                                                   self._db_values[_sub_refkey.strip()]))

                        self._db_values[_insertkey][_sub_insertkey] = self._db_values[_sub_refkey]

            elif self._db_values.get(_refkey):
                if _refkey not in self.do_not_display:
                    self.logger.debug(f'4523465: mapped key ["{_insertkey}"] -> _refkey "{_refkey}"')

                self._db_values[_insertkey] = self._db_values[_refkey]

            elif not self._db_values.get(_refkey):
                self.logger.warn(f'mapped key: refkey not found "{_refkey} for insertkey "{_insertkey}"')

    def _insert_tf_add_keys(self):

        count = 0
        for resource in self.tfstate_values["resources"]:
            type = resource["type"]
            name = resource["name"]
            if resource["type"] == self.terraform_type:
                self.logger.debug(f'name: {name}, type: {type} matched found')
                count += 1

        # if more than instance of the terraform type, it's better to parse the statefile
        # after to allowing querying of resources
        if count > 1:
            existing_names = []
            self.logger.warn(f"more than one instance terraform type {self.terrraform_type}/count {count} - skipping to avoid duplicates")
            if self._db_values.get("main") and self._db_values.get("name") and self._db_values.get("terraform_type") and not self._db_values.get("id"):
                name = self._db_values["name"]
                if name in existing_names:
                    raise Exception("cannot determine id => name + terraform_type + main are not unique")
                self._db_values["id"] = get_hash({
                    "name": self._db_values["name"],
                    "terraform_type": self._db_values["terraform_type"],
                    "main": "True"
                })
            return

        self._db_values["last_applied"]["tf"]["exec"]["skip_keys"] = self.tf_exec_skip_keys
        self._db_values["last_applied"]["tf"]["exec"]["add_keys"] = self.tf_exec_add_keys

        for resource in self.tfstate_values["resources"]:

            if resource["type"] == self.terraform_type:

                self.logger.debug("-" * 32)
                self.logger.debug("instance attribute keys")
                self.logger.debug(list(resource["instances"][0]["attributes"].keys()))
                self.logger.debug("-" * 32)

                for _key,_value in resource["instances"][0]["attributes"].items():

                    if not _value:
                        continue

                    if _key in self._db_values:
                        continue

                    if _key in self.tf_exec_skip_keys:
                        self.logger.debug('tf_exec_skip_keys: tf instance attribute key "{}" skipped'.format(_key))
                        continue

                    # we add if tf_exec_add_key not set, all, or key is in it
                    if not self.tf_exec_add_keys:
                        _added_bc = "tf_exec_add_keys=None"
                    elif self.tf_exec_add_keys == "all":
                        _added_bc = "tf_exec_add_keys=all"
                    elif _key in self.tf_exec_add_keys:
                        _added_bc = "tf_exec_add_keys/key{} found".format(_key)
                    else:
                        _added_bc = None

                    if not _added_bc:
                        self.logger.debug("tf_exec_add_keys: key {} skipped".format(_key))
                        continue

                    self._db_values["last_applied"]["tf"]["added"].append(_added_bc)

                    self.logger.debug('{}: tf key "{}" -> value "{}" added to resource self._db_values'.format(_added_bc,
                                                                                                      _key,
                                                                                                      _value))

                    if isinstance(_value,list):
                        try:
                            self._db_values[_key] = ",".join(_value)
                        except:
                            self._db_values[_key] = _value
                    elif isinstance(_value,dict):
                        try:
                            self._db_values[_key] = json.dumps(_value)
                        except:
                            self._db_values[_key] = _value
                    else:
                        self._db_values[_key] = _value
                break

    def _insert_tf_remove_keys(self):

        if not self.tf_exec_remove_keys:
            return

        self._db_values["last_applied"]["tf"]["exec"]["remove_keys"] = self.tf_exec_remove_keys

        return

    def _insert_tf_outputs(self):

        try:
            outputs = self.tfstate_values["outputs"]
        except:
            outputs = None

        if not outputs:
            return

        self._db_values["last_applied"]["tf"]["exec"]["outputs"] = outputs

        # put outputs in
        for k,v in outputs.items():

            # skip certain keys
            if k in self.tf_output_skip_keys:
                continue

            # already set and exists
            if self._db_values.get(k):
                continue

            self._db_values[k] = v['value']
            self._db_values["last_applied"]["tf"]["added"].append(k)

    def insert_frm_tfstate_to_values(self):

        try:
            self._insert_tf_outputs()
        except:
            self.logger.warn("_insert_tf_outputs failed")

        try:
            self._insert_tf_add_keys()
        except:
            self.logger.warn("_insert_tf_add_keys failed")

        try:
            self._insert_tf_map_keys()
        except:
            self.logger.warn("_insert_tf_map_keys failed")

        try:
            self._insert_tf_remove_keys()
        except:
            self.logger.warn("_insert_tf remove keys failed")

        return

    # duplicate wertqttetqwetwqtqwt
    def _insert_standard_resource_labels(self):

        for key in self.std_labels_keys:

            if not self._db_values.get(key):
                self.logger.debug('source standard label key "{}" not found'.format(key))
                continue

            label_key = "label-{}".format(key)

            if self._db_values.get(label_key):
                self.logger.debug('label key "{}" already found'.format(label_key))
                continue

            self._db_values[label_key] = self._db_values[key]

    def _insert_resource_labels(self):

        if not self.resource_labels:
            return

        for _k,_v in self.resource_labels.items():
            self.logger.debug(f'resource labels: key "{"label-{}".format(_k)}" -> value "{_v}"')
            self._db_values["label-{}".format(_k)] = _v

    def _insert_resource_values(self):
        """
        This method inserts the resource self._db_values into the output self._db_values.
        """
        if not self.resource_values:
            return

        for _k, _v in self.resource_values.items():
            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug(f"resource values: key \"{_k}\" -> value \"{_v}\"")
            self._db_values[_k] = _v

    def _set_parse_settings_for_tfstate(self):

        # new version of resource setttings
        resource_configs = self.tf_configs.get("resource_configs")

        if resource_configs and resource_configs.get("include_keys"):
            self.tf_exec_add_keys = resource_configs["include_keys"]

        if resource_configs and resource_configs.get("exclude_keys"):
            self.tf_exec_remove_keys.extend(resource_configs["exclude_keys"])

        if resource_configs and resource_configs.get("map_keys"):
            self.tf_exec_map_keys = resource_configs["map_keys"]
            # special cloud specific mappings of resource keys
            if self.provider == "aws":
                self.tf_exec_map_keys.update({"region": "aws_default_region"})
            elif self.provider == "do":
                self.tf_exec_map_keys.update({"region": "do_region"})

    def _remove_and_record_existing_values(self):

        if not self._last_applied_add_keys:
            return

        for _k in self._last_applied_add_keys:
            if _k not in self._db_values:
                continue
            self._db_removed_values[_k] = self._db_values[_k]

    def configure(self):

        self._setup_for_configuration()

        self._insert_resource_values()
        self._insert_resource_labels()
        self._insert_standard_resource_labels()

class Testtest456:

    def __init__(self):

        print("This is only for testing and served as a placeholder")

    #################################################################
    # fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    # insert 3453452345
    # insert back into TFExecShellHelper
    # fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    #################################################################

    def _set_runtime_env_vars(self,method="create"):

        if method == "create":
            try:
                exclude_vars = list(self.tf_configs["tf_vars"].keys())
            except:
                exclude_vars = self.exclude_tfvars

            # insert TF_VAR_* os vars
            self.insert_os_env_prefix_envs(self.build_env_vars,
                                           exclude_vars)

            # this should be set by ResourceCmdHelper
            self.build_env_vars["BUILD_TIMEOUT"] = self.build_timeout  # this should be set by Config0SettingsEnvVarHelper

            if self.docker_image:  # this should be set by Config0SettingsEnvVarHelper
                self.build_env_vars["DOCKER_IMAGE"] = self.docker_image

            if self.runtime_env_vars:
                for _k,_v in self.runtime_env_vars.items():
                    self.build_env_vars[_k] = _v

        self.build_env_vars["TF_RUNTIME"] = self.tf_runtime  # this should be set by Config0SettingsEnvVarHelper
        self.build_env_vars["SHARE_DIR"] = self.share_dir  # this should be set by ResourceCmdHelper
        self.build_env_vars["RUN_SHARE_DIR"] = self.run_share_dir  # this should be set by ResourceCmdHelper
        self.build_env_vars["LOG_BUCKET"] = self.log_bucket  # this should be set by ResourceCmdHelper
        self.build_env_vars["TMP_BUCKET"] = self.tmp_bucket  # this should be set by ResourceCmdHelper
        self.build_env_vars["STATEFUL_ID"] = self.stateful_id  # this should be set by ResourceCmdHelper
        self.build_env_vars["APP_DIR"] = self.app_dir  # this should be set by ResourceCmdHelper
        self.build_env_vars["APP_NAME"] = self.app_name  # this should be set by ResourceCmdHelper
        self.build_env_vars["REMOTE_STATEFUL_BUCKET"] = self.remote_stateful_bucket  # this should be set by ResourceCmdHelper
        self.build_env_vars["TMPDIR"] = "/tmp"

        # ssm name setting
        if self.build_env_vars.get("SSM_NAME"):  # usually set in create
            self.ssm_name = self.build_env_vars["SSM_NAME"]
        elif os.environ.get("SSM_NAME"):
            self.ssm_name = os.environ["SSM_NAME"]

        if self.ssm_name:
            self.build_env_vars["SSM_NAME"] = self.ssm_name

        return

    # create terraform.tfvars file from TF_VAR_* variables
    def _create_terraform_tfvars(self):

        if self.tf_configs and self.tf_configs.get("tf_vars"):
            _tfvars = self.tf_configs["tf_vars"]
        else:
            _tfvars = self.get_os_env_prefix_envs()

        if not _tfvars:
            return

        with open(self.terraform_tfvars,"w") as f:

            for _key,_input in _tfvars.items():
                _type = _input["type"]

                if _type == "dict":
                    _value = tf_iter_to_str(_input["value"])
                    _quoted = None
                elif _type == "list":
                    _value = tf_iter_to_str(_input["value"])
                    _quoted = None
                elif _type == "bool":
                    _quoted = None
                    _value = get_tf_bool(_input["value"])
                elif _type == "float":
                    _value = _input["value"]
                    _quoted = None
                elif _type == "int":
                    _value = _input["value"]
                    _quoted = None
                else:
                    _value = _input["value"]
                    _quoted = True

                self.logger.debug("_create_terraform_tfvars (new_format): {} -> <{}> {}".format(_key,
                                                                                                _type,
                                                                                                _value))

                if _quoted:
                    _entry = '{} \t= "{}"'.format(_key,_value)
                else:
                    _entry = '{} \t= {}'.format(_key,_value)

                f.write(_entry)
                f.write("\n")

        self.logger.debug("*" * 32)
        self.logger.debug("")
        self.logger.debug("Wrote terraform.tfvars: {}".format(self.terraform_tfvars))
        self.logger.debug("")
        self.logger.debug("*" * 32)

        return _tfvars.keys()

    # aws codebuild/lambda are the tf executors for apply/destroy/validate
    def _get_aws_exec_cinputargs(self,method="create"):

        cinputargs = {
            "method": method,
            "build_timeout": self.build_timeout,
            "run_share_dir": self.run_share_dir,
            "app_dir": self.app_dir,
            "remote_stateful_bucket": self.remote_stateful_bucket,
            "aws_region": self.aws_region
        }

        if self.build_env_vars:
            cinputargs["build_env_vars"] = self.build_env_vars

        if self.ssm_name:
            cinputargs["ssm_name"] = self.ssm_name

        cinputargs.update({
            "version": self.version,
            "binary": self.binary
        })

        return cinputargs

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

    def create_aws_tf_backend(self):

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
        with open(_file,"w") as file:
            file.write(contents)

    def _setup_and_exec_in_aws(self,method,create_remote_state=None):

        self._set_runtime_env_vars(method=method)
        self._set_build_method()

        # use backend to track state file
        if create_remote_state:
            self.create_aws_tf_backend()

        return self._exec_in_aws(method=method)

    def _exec_in_aws(self,method="create"):

        cinputargs = self._get_aws_exec_cinputargs(method=method)

        if self.build_method == "lambda":
            _awsbuild = Lambdabuild(**cinputargs)
        elif self.build_method == "codebuild":
            _awsbuild = Codebuild(**cinputargs)
        else:
            return False

        # submit and run required env file
        if method == "create":
            # ref 4354523
            self.create_build_envfile(encrypt=None,
                                      openssl=False)

        results = _awsbuild.run()

        self.eval_log(results,
                      prt=True)

        if method == "destroy":
            try:
                os.chdir(self.cwd)
            except:
                os.chdir("/tmp")

        self.eval_failure(results,
                          method)

        return results

    def create(self):

        if not self.stateful_id:
            self.logger.error("STATEFUL_ID needs to be set")

        # if we render template files, we don't create tfvars file
        if not self.templify(app_template_vars="TF_EXEC_TEMPLATE_VARS",**self.inputargs):
            self.exclude_tfvars = self._create_terraform_tfvars()

        if not os.path.exists(self.exec_dir):
            failed_message = "terraform directory must exists at {} when creating tf".format(self.exec_dir)
            raise Exception(failed_message)

        tf_results = self._setup_and_exec_in_aws("create",
                                                 create_remote_state=True)  # testtest456
        #create_remote_state = self.create_remote_state)

        self._post_create()

        return tf_results

    def run(self):

        if self.method == "create":
            self.create()
        elif self.method == "destroy":
            self._setup_and_exec_in_aws("destroy")
        elif self.method == "validate":
            self._setup_and_exec_in_aws("validate")
        else:
            usage()
            print('method "{}" not supported!'.format(self.method))
            exit(4)

    #############################################################
    # post create related
    #############################################################
    def _get_init_db_values(self):

        tfstate_values = get_tfstate_file_remote(self.remote_stateful_bucket,
                                                 self.stateful_id)

        if not tfstate_values:
            self.logger.debug("u4324: no data to retrieved from statefile")
            return False

        self.logger.debug("u4324: retrieved data from statefile")

        # testtest456
        # revisit 324214
        values = {
            "last_applied": {
                "tf": {
                    "exec": {},
                    "added": []
                }},
            "raw": {"terraform": b64_encode(tfstate_values)},
            "source_method": "terraform",
            "main": True,
            "provider": self.provider,
            "terraform_type": self.terraform_type,
            "resource_type": self.resource_type,
            "stateful_id":self.stateful_id,
            "remote_stateful_bucket": self.remote_stateful_bucket
        }

        if os.environ.get("CONFIG0_RESOURCE_EXEC_SETTINGS_HASH"):
            values["CONFIG0_RESOURCE_EXEC_SETTINGS_HASH"] = os.environ["CONFIG0_RESOURCE_EXEC_SETTINGS_HASH"]

        # special case of ssm_name/secrets
        if self.ssm_name:
            values["ssm_name"] = self.ssm_name

        return values

    def _insert_mod_params(self,resource):

        '''
        - we typically load the modifications parameters along with created resource like a
        VPC or database

        - the resource is therefore self contained, whereby it specifies to the
        system how it can be validated/destroyed.

        - for terraform, we include things like the docker image used to
        validate/destroy the resource and any environmental variables
        '''

        # environmental variables to include during destruction
        env_vars = {
            "REMOTE_STATEFUL_BUCKET": self.remote_stateful_bucket,
            "STATEFUL_ID": self.stateful_id,
            "BUILD_TIMEOUT": self.build_timeout,
            "APP_NAME": "terraform",
            "APP_DIR": self.app_dir
        }

        env_vars["TF_RUNTIME"] = self.tf_runtime

        # Create mod params resource arguments and reference
        resource["mod_params"] = {
            "env_vars": env_vars,
        }

        if self.shelloutconfig:
            resource["mod_params"]["shelloutconfig"] = self.shelloutconfig

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
                "env_vars": dict({"METHOD": "validate"},
                                 **self.validate_env_vars)
            }
        else:
            resource["validate_params"] = {
                "env_vars": {"METHOD": "validate"}
            }

        return resource
    def _post_create(self):

        # copy of settings file
        # revisit 324125
        # testtest456  no sure this is needed
        #self.write_config0_settings_file()

        # it succeeds at this point
        # parse tfstate file
        os.chdir(self.exec_dir)

        self.logger.debug("u4324: getting resource from standard init_tfstate_to_output")

        resource = self._get_init_db_values()

        if not resource:
            self.logger.warn("u4324: resource info is not found in the output")
            return

        self._insert_mod_params(resource)

        os.chdir(self.cwd)

        # testtest456
        if hasattr(self,"drift_protection") and self.drift_protection:
            self._db_values["drift_protection"] = self.drift_protection

        _configure = ConfigureTFforConfig0Db(db_values=resource)
        _configure.configure()
        # testtest456

        # enter into resource db through
        # file location or through standard out
        self.write_resource_to_json_file(resource,
                                         must_exist=True)

        return True
    #################################################################
    # fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    #################################################################

def usage():
    print('testtest456')
