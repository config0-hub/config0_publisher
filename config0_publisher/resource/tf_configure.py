#!/usr/bin/env python

import os
from config0_publisher.terraform import get_tfstate_file_remote
from config0_publisher.cloud.aws.boto3_s3 import dict_to_s3

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
            "resource_type": self.resource_type,
            "stateful_id":self.stateful_id,
            "remote_stateful_bucket": self.remote_stateful_bucket
        }

        try:
            self.db_values["terraform_type"] = self.terraform_type
        except Exception:
            self.logger.warn("terraform_type is not available")

        # special case of ssm_name/secrets
        if self.ssm_name:
            self.db_values["ssm_name"] = self.ssm_name

        return self.db_values

    def _insert_mod_params(self):

        """
        - we typically load the modifications parameters along with created resource like a
        VPC or database

        - the resource is therefore self contained, whereby it specifies to the
        system how it can be validated/destroyed.

        - for terraform, we include things like the docker image used to
        validate/destroy the resource and any environmental variables
        """

        # environmental variables to include during destruction
        #"CONFIG0_RESOURCE_EXEC_SETTINGS_HASH": self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH,

        env_vars = {
            "REMOTE_STATEFUL_BUCKET": self.remote_stateful_bucket,
            "STATEFUL_ID": self.stateful_id,
            "BUILD_TIMEOUT": self.build_timeout,
            "TF_RUNTIME": self.tf_runtime,
            "APP_NAME": "terraform",
            "APP_DIR": self.app_dir
        }

        # testtest456
        self.logger.debug('j5'*32)
        self.logger.json(env_vars)
        self.logger.debug('j5'*32)

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
                self.logger.debug(f'source standard label key "{key}" not found')
                continue

            label_key = f"label-{key}"

            if self.db_values.get(label_key):
                self.logger.debug(f'label key "{label_key}" already found')
                continue

            self.db_values[label_key] = self.db_values[key]

    def _insert_resource_labels(self):

        if not self.resource_labels:
            return

        for _k,_v in self.resource_labels.items():
            self.logger.debug(f'resource labels: key "{f"label-{_k}"}" -> value "{_v}"')
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

    def _insert_outputs(self):

        # testtest456
        print('s0'*32)
        print('s0'*32)
        print('s0'*32)

        try:
            tfstate_values = get_tfstate_file_remote(self.remote_stateful_bucket,
                                                     self.stateful_id)
        except:
            tfstate_values = None

        print('s1'*32)
        print('s1'*32)
        print('s1'*32)

        if not tfstate_values:
            return

        # put outputs in
        for k,v in tfstate_values["outputs"]:

            # already set and exists
            if self.db_values.get(k):
                continue

            self.db_values[k] = v['value']

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
        self._insert_maps()

        # this will put the initial outputs from last run
        # these outputs can cause problems later if they change
        # if the outputs are used for querying
        self._insert_outputs()

        # default script to process the tfstate and
        # merge it the db_values for a complete response
        if not self.db_values.get("_eval_state_script"):
            self.db_values["_eval_state_script"] = "config0-publish:::terraform::transfer_db_results"

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
