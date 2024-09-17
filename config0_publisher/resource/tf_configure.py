#!/usr/bin/env python
#

import os
import json
from ast import literal_eval
from time import sleep

from config0_publisher.shellouts import execute3
from config0_publisher.serialization import b64_decode
from config0_publisher.serialization import decode_and_decompress_string
from config0_publisher.loggerly import Config0Logger
from config0_publisher.loggerly import nice_json
from jiffycommon.utilities import id_generator2
from config0_publisher.utilities import get_hash
###########################
from config0_publisher.resource.tf_vars import tf_iter_to_str
from config0_publisher.resource.tf_vars import get_tf_bool
from config0_publisher.serialization import b64_encode
from config0_publisher.resource.codebuild import Codebuild
from config0_publisher.resource.lambdabuild import Lambdabuild
from config0_publisher.terraform import get_tfstate_file_remote
from config0_publisher.cloud.aws.boto3_s3 import dict_to_s3
#from config0_publisher.cloud.aws.boto3_s3 import s3_to_dict

class ConfigureTFConfig0Db:

    def __init__(self):

        self.classname = "ConfigureTFConfig0Db"

        self.std_labels_keys = [
            "region",
            "provider",
            "source_method",
            "resource_type",
        ]

    def _set_init_db_values(self):

        self.db_values = {
            "source_method": "terraform",
            "main": True,
            "provider": self.provider,
            "terraform_type": self.terraform_type,
            "resource_type": self.resource_type,
            "stateful_id":self.stateful_id,
            "remote_stateful_bucket": self.remote_stateful_bucket
        }

        # special case of ssm_name/secrets
        if self.ssm_name:
            self.db_values["ssm_name"] = self.ssm_name

        return self.db_values

    def _insert_mod_params(self):

        '''
        - we typically load the modifications parameters along with created resource like a
        VPC or database

        - the resource is therefore self contained, whereby it specifies to the
        system how it can be validated/destroyed.

        - for terraform, we include things like the docker image used to
        validate/destroy the resource and any environmental variables
        '''

        # environmental variables to include during destruction
        # testtest456
        #"CONFIG0_RESOURCE_EXEC_SETTINGS_HASH": self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH,
        env_vars = {
            "REMOTE_STATEFUL_BUCKET": self.remote_stateful_bucket,
            "STATEFUL_ID": self.stateful_id,
            "BUILD_TIMEOUT": self.build_timeout,
            "APP_NAME": "terraform",
            "APP_DIR": self.app_dir
        }

        env_vars["TF_RUNTIME"] = self.tf_runtime

        # Create mod params resource arguments and reference
        self.db_values["mod_params"] = {
            "env_vars": env_vars,
        }

        if self.destroy_env_vars:
            self.db_values["destroy_params"] = {
                "env_vars": dict({"METHOD": "destroy"},
                                 **self.destroy_env_vars)
            }
        else:
            self.db_values["destroy_params"] = {
                "env_vars": {"METHOD": "destroy"}
            }

        if self.validate_env_vars:
            self.db_values["validate_params"] = {
                "env_vars": dict({"METHOD": "validate"},
                                 **self.validate_env_vars)
            }
        else:
            self.db_values["validate_params"] = {
                "env_vars": {"METHOD": "validate"}
            }

        if self.shelloutconfig:
            self.db_values["mod_params"]["shelloutconfig"] = self.shelloutconfig
            self.db_values["destroy_params"]["shelloutconfig"] = self.shelloutconfig
            self.db_values["validate_params"]["shelloutconfig"] = self.shelloutconfig

        if self.mod_execgroup:
            self.db_values["mod_params"]["execgroup"] = self.mod_execgroup
            self.db_values["destroy_params"]["shelloutconfig"] = self.shelloutconfig
            self.db_values["validate_params"]["shelloutconfig"] = self.shelloutconfig

    def _insert_standard_resource_labels(self):

        for key in self.std_labels_keys:

            if not self.db_values.get(key):
                self.logger.debug('source standard label key "{}" not found'.format(key))
                continue

            label_key = "label-{}".format(key)

            if self.db_values.get(label_key):
                self.logger.debug('label key "{}" already found'.format(label_key))
                continue

            self.db_values[label_key] = self.db_values[key]

    def _insert_resource_labels(self):

        if not self.resource_labels:
            return

        for _k,_v in self.resource_labels.items():
            self.logger.debug(f'resource labels: key "{"label-{}".format(_k)}" -> value "{_v}"')
            label_key = f"label-{_k}"
            self.db_values[label_key] = _v

    def _insert_maps(self):
        """
        This method inserts the resource self.db_values into the output self.db_values.
        """

        if not self.tf_configs.get("maps"):
            return

        for _k,_v in self.tf_configs.get("maps").items():

            if not self.db_values.get(_k):
                continue

            self.logger.debug(f"resource values: key \"{_k}\" -> value \"{_v}\"")
            self.db_values[_k] = _v

    def _insert_resource_values(self):
        """
        This method inserts the resource self.db_values into the output self.db_values.
        """
        if not self.resource_values:
            return

        for _k, _v in self.resource_values.items():
            self.logger.debug(f"resource values: key \"{_k}\" -> value \"{_v}\"")
            self.db_values[_k] = _v

    def _get_query_settings_for_tfstate(self):

        # new version of resource setttings
        tf_configs_for_resource = self.tf_configs.get("resource_configs")

        if not tf_configs_for_resource:
            return {}

        return {
            "include_keys":tf_configs_for_resource.get("include_keys"),
            "exclude_keys": tf_configs_for_resource.get("exclude_keys"),
            "maps": tf_configs_for_resource.get("maps")
        }

    def _config_db_values(self):

        tfstate_values = get_tfstate_file_remote(self.remote_stateful_bucket,
                                                 self.stateful_id)

        if not self.db_values.get("id"):

            for resource in tfstate_values["resources"]:

                if resource["type"] != self.terraform_type:
                    continue

                try:
                    self.db_values["id"] = resource["instances"][0]["attributes"]["id"]
                except:
                    self.db_values["id"] = None

                if not self.db_values.get("id"):
                    try:
                        self.db_values["id"] = resource["instances"][0]["attributes"]["arn"]
                    except:
                        self.db_values["id"] = None

            if not self.db_values.get("id"):
                self.db_values["id"] = self.stateful_id

        if not self.db_values.get("_id"):
            self.db_values["_id"] = self.stateful_id

    def post_create(self):

        # it succeeds at this point
        # parse tfstate file
        os.chdir(self.exec_dir)

        self.logger.debug("u4324: getting resource from standard init_tfstate_to_output")

        self._set_init_db_values()

        if not self.db_values:
            self.logger.warn("u4324: resource info is not found in the output")
            return

        self._insert_mod_params()

        os.chdir(self.cwd)

        if hasattr(self,"drift_protection") and self.drift_protection:
            self.db_values["drift_protection"] = self.drift_protection

        # write apply and query parameters to s3 bucket
        self._insert_resource_values()
        self._insert_resource_labels()
        self._insert_standard_resource_labels()
        # testtest456
        self._insert_maps()

        # default script to process the tfstate and
        # merge it the db_values for a complete response
        if not self.db_values.get("_eval_state_script"):
            self.db_values["_eval_state_script"] = "config0-publish:::terraform::transfer_db_results"

        # insert id and _id
        self._config_db_values()

        # enter into resource db file location
        self.write_resource_to_json_file(self.db_values,
                                         must_exist=True)

        db_resource_params = {
            "std_labels":self.std_labels_keys,
            "labels":self.resource_labels,
            "values":self.resource_values
        }

        tf_filter_params = self._get_query_settings_for_tfstate()

        s3_base_key = f'{self.stateful_id}/main'

        dict_to_s3({"config0_resource_exec_settings_hash":self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH},
                   self.remote_stateful_bucket,
                   f'{s3_base_key}/init/config0_resource_exec_settings_hash.{self.stateful_id}')

        dict_to_s3(db_resource_params,
                   self.remote_stateful_bucket,
                   f'{s3_base_key}/applied/resource_configs_params.{self.stateful_id}')

        dict_to_s3(tf_filter_params,
                   self.remote_stateful_bucket,
                   f'{s3_base_key}/query/execution/tf_filter_params.{self.stateful_id}')

        return True

    #################################################################
    # fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    #################################################################

class Testtest456(ConfigureTFConfig0Db):

    def __init__(self):

        print("This is only for testing and served as a placeholder")

        ConfigureTFConfig0Db.__init__(self)

    #################################################################
    # fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    # insert 3453452345
    # insert back into TFExecShellHelper
    # fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
    #################################################################
    def _set_runtime_env_vars(self,method="create"):

        # ref 43532453
        # build_env_vars only needed when initially creating
        if method != "create":
            return

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

    # aws codebuild/lambda are the tf executors for apply/destroy/apply/pre-create/validate
    def _get_aws_exec_cinputargs(self,method="create"):

        cinputargs = {
            "method": method,
            "build_timeout": self.build_timeout,
            "run_share_dir": self.run_share_dir,
            "app_dir": self.app_dir,
            "remote_stateful_bucket": self.remote_stateful_bucket,
            "aws_region": self.aws_region
        }

        # usually associated with create
        if method in ["apply","create","pre-create"]:
            if self.build_env_vars:
                cinputargs["build_env_vars"] = self.build_env_vars

            if self.ssm_name:
                cinputargs["ssm_name"] = self.ssm_name

        # usually associated with destroy/validate/check
        elif os.environ.get("CONFIG0_BUILD_ENV_VARS"):
            cinputargs["build_env_vars"] = b64_decode(os.environ["CONFIG0_BUILD_ENV_VARS"])

        cinputargs.update({
            "version": self.version,
            "binary": self.binary,
            "tf_runtime": self.tf_runtime
        })

        return cinputargs

    def _set_build_method(self):

        # for testing
        # testtest456
        #os.environ["USE_LAMBDA"] = "True"
        os.environ["USE_CODEBUILD"] = "True"

        if os.environ.get("USE_CODEBUILD"):  # longer than 900 seconds
            self.build_method = "codebuild"
        elif os.environ.get("USE_LAMBDA"):  # shorter than 900 seconds
            self.build_method = "lambda"
        elif self.method in ["validate", "check", "pre-create"]:
            self.build_method = "lambda"
        elif os.environ.get("USE_AWS",True):  # select codebuild or lambda
            if int(self.build_timeout) > 600:
                self.build_method = "codebuild"
            else:
                self.build_method = "lambda"
        else:  # the default
            self.build_method = "lambda"

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
    key    = "{self.stateful_id}/state/{self.stateful_id}.tfstate"
    region = "{self.aws_region}"
  }}
}}

"""
        with open(_file,"w") as file:
            file.write(contents)

    def _setup_and_exec_in_aws(self,method,create_remote_state=None):

        self._set_runtime_env_vars(method=method)

        # use backend to track state file
        if create_remote_state:
            self.create_aws_tf_backend()

        return self._exec_in_aws(method=method)

    def _exec_in_aws(self,method="create"):

        cinputargs = self._get_aws_exec_cinputargs(method=method)

        _awsbuild_lambda = Lambdabuild(**cinputargs)

        # ref 435353245634
        # mod params and env_vars
        if self.build_method == "lambda":
            _awsbuild = _awsbuild_lambda
        elif self.build_method == "codebuild":
            _awsbuild = Codebuild(**cinputargs)
        else:
            return False

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

        self._set_runtime_env_vars(method="create")
        self.create_aws_tf_backend()

        # submit and run required env file
        # ref 4354523
        self.create_build_envfile(encrypt=None,
                                  openssl=False)

        if self.build_method == "codebuild":
            self.build_method = "lambda"  # we run pre-create in lambda first
            _use_codebuild = True
        else:
            _use_codebuild = None

        pre_creation = self._exec_in_aws(method="pre-create")

        if not pre_creation.get("status"):
            raise Exception("pre-create failed")
        else:
            self.logger.debug("pre-creation succeeded")

        if _use_codebuild:
            self.build_method = 'codebuild'

        tf_results = self._exec_in_aws(method="create")

        self.post_create()

        return tf_results

    def run(self):

        self._set_build_method()

        if self.method == "create":
            self.create()
        elif self.method == "destroy":
            self._setup_and_exec_in_aws("destroy")
        elif self.method == "validate":
            self._setup_and_exec_in_aws("validate")
        elif self.method == "check":
            self._setup_and_exec_in_aws("check")
        else:
            usage()
            print('method "{}" not supported!'.format(self.method))
            exit(4)

def usage():
    print('testtest456')
