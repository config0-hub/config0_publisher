#!/usr/bin/env python

import os
import shutil
from time import sleep
from config0_publisher.utilities import get_values_frm_json
from config0_publisher.utilities import to_jsonfile
from config0_publisher.serialization import b64_encode
from config0_publisher.serialization import b64_decode
from config0_publisher.shellouts import rm_rf

# ref 34532045732
class ResourcePhases:

    def __init__(self, **kwargs):
        self.classname = 'ResourcePhases'
        self.phases_params_hash = kwargs.get("phases_params_hash")
        self.phases_params = kwargs.get("phases_params")
        self.phases_info = None
        self.phase = None  # can be "run" since will only one phase
        self.current_phase = None
        self._set_phases_params()

    def set_phases_json(self):

        if not hasattr(self, "config0_phases_json_file") or not self.config0_phases_json_file:
            self.config0_phases_json_file = os.environ.get("CONFIG0_PHASES_JSON_FILE")

        if not self.config0_phases_json_file:
            try:
                self.config0_phases_json_file = os.path.join(self.stateful_dir,
                                                             f"phases-{self.stateful_id}.json")
            except:
                self.config0_phases_json_file = None

        self.logger.debug(f'u4324: CONFIG0_PHASES_JSON_FILE "{self.config0_phases_json_file}"')

    def _set_phases_params(self):
        if self.phases_params_hash:
            return

        if self.phases_params:
            self.phases_params_hash = b64_encode(self.phases_params)
            return

        if os.environ.get("PHASES_PARAMS_HASH"):
            self.phases_params_hash = os.environ.get("PHASES_PARAMS_HASH")
            return

    def delete_phases_to_json_file(self):
        if not hasattr(self, "config0_phases_json_file"):
            self.logger.debug("delete_phases_to_json_file - config0_phases_json_file not set")
            return

        if not self.config0_phases_json_file:
            return

        if not os.path.exists(self.config0_phases_json_file):
            return

        rm_rf(self.config0_phases_json_file)

    def write_phases_to_json_file(self, content_json):
        if not hasattr(self, "config0_phases_json_file"):
            self.logger.debug("write_phases_to_json_file - config0_phases_json_file not set")
            return

        if not self.config0_phases_json_file:
            return

        self.logger.debug(f"u4324: inserting retrieved data into {self.config0_phases_json_file}")

        to_jsonfile(content_json,
                    self.config0_phases_json_file)

class ReferenceNotUsedResourcePhases:

    def __init__(self, **kwargs):
        pass

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

    def _get_next_phase(self, method="create", **json_info):
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

        # Using shutil to remove directory
        shutil.rmtree(self.run_share_dir, ignore_errors=True)

        self.logger.error("Cannot determine next phase to run - reset")
        raise Exception("Cannot determine next phase to run")

    def set_cur_phase(self):
        """
        self.phases_params_hash = None
        self.phases_params = None
        self.phases_info = None
        self.phase = None  # can be "run" since will only one phase
        self.current_phase None
        """

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

        def jsonfile_to_phases_info(self):
            if not hasattr(self, "config0_phases_json_file"):
                self.logger.debug("jsonfile_to_phases_info - config0_phases_json_file not set")
                return

        if not self.config0_phases_json_file:
            return

        if not os.path.exists(self.config0_phases_json_file):
            return

        self.phases_info = get_values_frm_json(json_file=self.config0_phases_json_file)






