#!/usr/bin/env python
#

import os

from config0_publisher.serialization import b64_decode
from config0_publisher.serialization import decode_and_decompress_string
from config0_publisher.loggerly import Config0Logger
from config0_publisher.loggerly import nice_json

class Config0SettingsEnvVarHelper:

    def __init__(self):

        self.classname = "Config0SettingsEnvVarHelper"

        self.logger = Config0Logger(self.classname,
                                    logcategory="cloudprovider")

        self._vars = {
            "runtime_env_vars":{},
            "exclude_tfvars":[],
            "build_env_vars":{}
        }

    def _set_frm_config0_resource_settings(self,raise_on_error=None):

        """
        This method initializes the Config0 resource settings.
        """

        self.CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH = os.environ.get("CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH")
        self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH = os.environ.get("CONFIG0_RESOURCE_EXEC_SETTINGS_HASH")

        if self.CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH:
            try:
                _settings = decode_and_decompress_string(self.CONFIG0_RESOURCE_EXEC_SETTINGS_ZLIB_HASH)
            except Exception:
                _settings = {}  # probably destroy
        elif self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH:
            try:
                _settings = b64_decode(self.CONFIG0_RESOURCE_EXEC_SETTINGS_HASH)
            except Exception:
                _settings = {}  # probably destroy
        else:
            _settings = {}

        if not _settings:
            failed_message = "The settings is empty for CONFIG0_RESOURCE_EXEC_SETTINGS_HASH"
            if raise_on_error:
                raise Exception(failed_message)
            self.logger.warn(failed_message)
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
            if self._vars["tf_configs"].get("terraform_type"):
                self._vars["terraform_type"] = self._vars["tf_configs"]["terraform_type"]

    def _set_tf_runtime(self):

        try:
            tf_runtime = self._vars["tf_configs"].get("tf_runtime")
        except Exception:
            tf_runtime = None

        if tf_runtime:
            self.logger.debug(f'tf_runtime {tf_runtime} from "tf_configs"')
            self._vars["tf_runtime"] = tf_runtime
            return tf_runtime

        tf_runtime = os.environ.get("TF_RUNTIME")

        if tf_runtime:
            self.logger.debug(f'tf_runtime {tf_runtime} from env var "TF_RUNTIME"')
        else:
            tf_runtime = "tofu:1.9.1"
            self.logger.debug(f'using default tf_runtime "{tf_runtime}"')

        self._vars["tf_runtime"] = tf_runtime

        return tf_runtime

    def _set_tf_binary_version(self):

        try:
            self._vars["binary"],self._vars["version"] = self._vars["tf_runtime"].split(":")
        except Exception:
            self.logger.debug(f'could not evaluate tf_runtime - using default {self._vars["tf_runtime"]}"')
            self._vars["binary"] = "tofu"
            self._vars["version"] = "1.6.2"

        return self._vars["binary"],self._vars["version"]

    def eval_config0_resource_settings(self,method=None):

        self._set_frm_config0_resource_settings()
        self._set_tf_runtime()
        self._set_tf_binary_version()

        # if it is creating for the first time
        if method == "create" and not self._vars.get("resource_type"):
            raise Exception("resource_type needs to be set")

        if not self._vars.get("provider"):
            self.logger.warn("provider should be set")

        for k,v in self._vars.items():
            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug(f'{k} -> {nice_json(v)}')
            setattr(self,k,v)