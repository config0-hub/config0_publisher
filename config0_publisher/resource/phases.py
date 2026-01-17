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
            self.logger.debug("write_phases_to_json_file - config0_phases_json_file is None")
            return

        # Ensure the directory exists
        directory = os.path.dirname(self.config0_phases_json_file)
        if directory:  # Check if a directory path exists
            os.makedirs(directory, exist_ok=True)

        self.logger.debug(f"u4324: inserting retrieved data into {self.config0_phases_json_file}")

        to_jsonfile(content_json, self.config0_phases_json_file)