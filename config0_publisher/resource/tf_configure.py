#!/usr/bin/env python
#

import os
import jinja2
import glob
import json
from time import sleep

from config0_publisher.utilities import get_hash

# init and reconfigure (update)

class Config0ResourceTFVarsCommonConfig(object):

    def __init__(self,values=None):

        '''
        self.get_hash => import get_hash
        self.data => _get_tfstate_file_remote()_

        self.remote_stateful_bucket = values["remote_stateful_bucket"]
        self.stateful_id = values["stateful_id"]
        self.terraform_type = values["terraform_type"]

        self.tf_exec_skip_keys = values["update_settings"]["tf"]["exec"]["skip_keys"]
        self.tf_exec_add_keys = values["update_settings"]["tf"]["exec"]["add_keys"]
        self.tf_exec_map_keys = values["update_settings"]["tf"]["exec"]["map_keys"] = self.tf_exec_map_keys
        self.tf_exec_remove_keys = values["update_settings"]["tf"]["exec"]["remove_keys"]
        '''

        self.classname = "Config0ResourceTFVarsCommonConfig"

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

        self.tf_exec_include_raw = True

        self.tf_exec_add_keys = []

        self.tf_exec_remove_keys = [
            "private",
            "secret",
        ]

        self.tf_exec_map_keys = {}

        self.tf_exec_state_file = os.environ.get("TF_EXEC_STATE_FILE",
                                                 "terraform-tfstate")

        if values:

            self.remote_stateful_bucket = values["remote_stateful_bucket"]
            self.stateful_id = values["stateful_id"]
            self.terraform_type = values["terraform_type"]

            try:
                self.tf_exec_skip_keys = values["update_settings"]["tf"]["exec"]["skip_keys"]
            except:
                self.tf_exec_skip_keys = []

            try:
                self.tf_exec_add_keys = values["update_settings"]["tf"]["exec"]["add_keys"]
            except:
                self.tf_exec_add_keys = []

            try:
                self.tf_exec_map_keys = values["update_settings"]["tf"]["exec"]["map_keys"] = self.tf_exec_map_keys
            except:
                self.tf_exec_map_keys = []

            try:
                self.tf_exec_remove_keys = values["update_settings"]["tf"]["exec"]["remove_keys"]
            except:
                self.tf_exec_remove_keys = []



    def _insert_tf_map_keys(self,values):

        self.logger.debug("#" * 32)
        self.logger.debug("tfstate_to_output: tf_exec_map_keys")
        self.logger.json(self.tf_exec_map_keys)
        self.logger.debug("#" * 32)

        if not self.tf_exec_map_keys:
            return

        values["update_settings"]["tf"]["exec"]["map_keys"] = self.tf_exec_map_keys

        for _insertkey,_refkey in self.tf_exec_map_keys.items():

            '''
            # _insertkey = "p1"
            # _refkey = "q1"

            # _insertkey = values
            # _refkey = {"a":"b","c":"d"}
            # values["values"]["a"] = values["b"]
            '''

            if values.get(_insertkey):
                self.logger.warn(f"mapped key {_insertkey} already exists - clobbering")

            # see if _refkey is a subkey
            if isinstance(_refkey,dict):

                if not values.get(_insertkey):
                    values[_insertkey] = {}

                values["update_settings"]["tf"]["added"].append(_insertkey)

                for _sub_insertkey,_sub_refkey in _refkey.items():

                    if not values.get(_sub_refkey):
                        self.logger.debug(
                            f'mapped ref_key not found {_sub_refkey} for sub_insertkey {_sub_insertkey}')
                    # ref 432523543245
                    # do we want to nest 2 levels deep?
                    if "," in values[_sub_refkey]:
                        _sub_insertkey2,_subrefkey2 = values[_sub_refkey].split(",")

                        if _sub_insertkey2 not in self.do_not_display:
                            self.logger.debug('mapped key ["{}"]["{}"]["{}"] -> _sub_refky "{}"'.format(_insertkey,
                                                                                                        _sub_insertkey,
                                                                                                        _sub_insertkey2,
                                                                                                        values[_sub_refkey.strip()][_subrefkey2.strip()]))

                        values[_insertkey][_sub_insertkey] = values[_sub_refkey.strip()][_subrefkey2.strip()]

                    else:
                        if _sub_insertkey not in self.do_not_display:
                            self.logger.debug('mapped key ["{}"]["{}"] -> _sub_refkey "{}"'.format(_insertkey,
                                                                                                   _sub_insertkey,
                                                                                                   values[_sub_refkey.strip()]))

                        values[_insertkey][_sub_insertkey] = values[_sub_refkey]

            elif values.get(_refkey):
                if _refkey not in self.do_not_display:
                    self.logger.debug(f'4523465: mapped key ["{_insertkey}"] -> _refkey "{_refkey}"')

                values[_insertkey] = values[_refkey]

            elif not values.get(_refkey):
                self.logger.warn(f'mapped key: refkey not found "{_refkey} for insertkey "{_insertkey}"')

    def _insert_tf_add_keys(self,values):

        count = 0
        for resource in self.data["resources"]:
            type = resource["type"]
            name = resource["name"]
            if resource["type"] == self.terraform_type:
                self.logger.debug(f'name: {name}, type: {type} matched found')
                count += 1

        # if more than instance of the terraform type, it's better to parse the statefile
        # after to allowing querying of resources
        if count > 1:
            self.logger.warn(f"more than one instance terraform type {self.terrraform_type}/count {count} - skipping to avoid duplicates")
            if values.get("main") and values.get("name") and values.get("terraform_type") and not values.get("id"):
                values["id"] = self.get_hash({
                    "name": values["name"],
                    "terraform_type": values["terraform_type"],
                    "main": "True"
                })
            return

        values["update_settings"]["tf"]["exec"]["skip_keys"] = self.tf_exec_skip_keys
        values["update_settings"]["tf"]["exec"]["add_keys"] = self.tf_exec_add_keys

        for resource in self.data["resources"]:

            if resource["type"] == self.terraform_type:

                self.logger.debug("-" * 32)
                self.logger.debug("instance attribute keys")
                self.logger.debug(list(resource["instances"][0]["attributes"].keys()))
                self.logger.debug("-" * 32)

                for _key,_value in resource["instances"][0]["attributes"].items():

                    if not _value:
                        continue

                    if _key in values:
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

                    values["update_settings"]["tf"]["added"].append(_added_bc)

                    self.logger.debug('{}: tf key "{}" -> value "{}" added to resource values'.format(_added_bc,
                                                                                                      _key,
                                                                                                      _value))

                    if isinstance(_value,list):
                        try:
                            values[_key] = ",".join(_value)
                        except:
                            values[_key] = _value
                    elif isinstance(_value,dict):
                        try:
                            values[_key] = json.dumps(_value)
                        except:
                            values[_key] = _value
                    else:
                        values[_key] = _value
                break

    def _insert_tf_remove_keys(self,values):

        if not self.tf_exec_remove_keys:
            return

        values["update_settings"]["tf"]["exec"]["remove_keys"] = self.tf_exec_remove_keys

        self.add_resource_inputargs["remove_keys"] = self.tf_exec_remove_keys
        self.add_resource_inputargs["encrypt_fields"] = [ "raw" ]  # raw is appended to encrypted fields

        return

    def _insert_tf_outputs(self,values):

        try:
            outputs = self.data["outputs"]
        except:
            outputs = None

        if not outputs:
            return

        values["update_settings"]["tf"]["exec"]["outputs"] = outputs

        # put outputs in
        for k,v in outputs.items():

            # skip certain keys
            if k in self.tf_output_skip_keys:
                continue

            # already set and exists
            if values.get(k):
                continue

            values[k] = v['value']
            values["update_settings"]["tf"]["added"].append(k)

    def tfstate_to_output(self,values):

        try:
            self._insert_tf_outputs(values)
        except:
            self.logger.warn("_insert_tf_outputs failed")

        try:
            self._insert_tf_add_keys(values)
        except:
            self.logger.warn("_insert_tf_add_keys failed")

        try:
            self._insert_tf_map_keys(values)
        except:
            self.logger.warn("_insert_tf_map_keys failed")

        try:
            self._insert_tf_remove_keys(values)
        except:
            self.logger.warn("_insert_tf remove keys failed")

        return values
