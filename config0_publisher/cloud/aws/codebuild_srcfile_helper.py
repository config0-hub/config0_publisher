#!/usr/bin/env python

# Copyright 2025 Gary Leong gary@config0.com
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os

from config0_publisher.loggerly import Config0Logger
from config0_publisher.resource.manage import ResourceCmdHelper
from config0_publisher.cloud.aws.codebuild import CodebuildResourceHelper
from config0_publisher.serialization import b64_decode
from config0_publisher.fileutils import pyzip
from config0_publisher.utilities import id_generator2


class CodebuildSrcFileHelper(ResourceCmdHelper):

    def __init__(self):
        self.classname = 'CodebuildSrcFile'
        self.logger = Config0Logger(
            self.classname,
            logcategory="cloudprovider"
        )

        ResourceCmdHelper.__init__(
            self,
            main_env_var_key="CODEBUILD_PARAMS_HASH",
            app_name=os.environ["APP_NAME"],
            app_dir=os.environ["APP_DIR"],
            set_must_exists=[
                "tmp_bucket",
                "upload_bucket",
                "log_bucket"
            ],
            set_default_values={
                "build_image": "aws/codebuild/standard:4.0",
                "build_timeout": 500,
                "compute_type": "BUILD_GENERAL1_SMALL",
                "image_type": "LINUX_CONTAINER",
                "remote_stateful_bucket": None,
                "upload_bucket": None,
                "stateful_id": None,
                "buildspec_file": "buildspec.yml"
            }
        )

    def _write_phase2complete(self):
        pass

    def _read_phase2complete(self):
        pass

    def _set_phase2complete(self):

        if self._read_phase2complete():
            return True

        self._phase2complete = {
                "status": None,
                "build_id": None,
                "stateful": self.stateful_id,
                "tar_file": None,
        }

    def _get_fqn_app_dir_path(self):
        if os.environ.get("CODEBUILD_SRCFILE_DEBUG"):
            self.list_files_share_dir()
            self.list_files_exec_dir()
        return os.path.join(
            self.share_dir,
            self.stateful_id,
            self.app_dir
        )

    def list_files_share_dir(self):
        self.logger.debug("#" * 32)
        self.logger.debug(f"# share_dir {self.share_dir}")
        self.list_files(self.share_dir)
        self.logger.debug("#" * 32)

    def list_files_exec_dir(self):
        self.logger.debug("#" * 32)
        self.logger.debug(f"# exec_dir {self.exec_dir}")
        self.list_files(self.exec_dir)
        self.logger.debug("#" * 32)

    @staticmethod
    def list_files(directory):
        files = os.listdir(directory)
        for file in files:
            if not os.path.isfile(os.path.join(directory, file)):
                continue
            print(file)

    def get_buildspec(self):
        # get with provided b64 hash
        if self.buildspec_hash:
            return b64_decode(self.buildspec_hash)

        # get repo file and read contents
        buildspec_file = os.path.join(
            self._get_fqn_app_dir_path(),
            "src",
            self.buildspec_file
        )

        with open(buildspec_file, "r") as file:
            file_contents = file.read()

        return file_contents

    def _set_build_env_vars(self):
        if not self.build_env_vars:
            if "build_env_vars" in self.syncvars.main_vars:
                self.build_env_vars = self.syncvars.main_vars["build_env_vars"]
            else:
                self.build_env_vars = {}

        self.build_env_vars["TMPDIR"] = self.tmpdir
        self.build_env_vars["SHARE_DIR"] = self.share_dir
        self.build_env_vars["BUILD_TIMEOUT"] = self.build_timeout
        self.build_env_vars["APP_DIR"] = self.app_dir
        self.build_env_vars["APP_NAME"] = self.app_name
        self.build_env_vars["STATEFUL_ID"] = self.stateful_id
        self.build_env_vars["RUN_SHARE_DIR"] = self.run_share_dir
        self.build_env_vars["TMP_BUCKET"] = self.tmp_bucket
        self.build_env_vars["LOG_BUCKET"] = self.log_bucket

        # Set upload bucket
        if self.remote_stateful_bucket:
            self.build_env_vars["UPLOAD_BUCKET"] = self.remote_stateful_bucket
        else:
            self.build_env_vars["UPLOAD_BUCKET"] = self.tmp_bucket

        if self.docker_image:
            self.build_env_vars["DOCKER_IMAGE"] = self.docker_image

    def _tar_upload_s3(self):
        if self._phase2complete.get("tar_file") and os.path.exists(self._phase2complete.get("tar_file")):
            srcfile = self._phase2complete["tar_file"]
        else:
            abs_app_dir = self._get_fqn_app_dir_path()
            temp_filename = f'{id_generator2()}.zip'
            srcfile = pyzip(
                abs_app_dir,
                self.tmpdir,
                temp_filename,
                exit_error=True
            )
            self._phase2complete["tar_file"] = srcfile

        cmd = (f'aws s3 cp {srcfile} '
               f's3://{self.buildparams["build_env_vars"]["UPLOAD_BUCKET"]}/'
               f'{self.stateful_id}/state/src.{self.stateful_id}.zip --quiet')

        return self.execute(cmd)

    def _setup(self):
        self._set_build_env_vars()

        self.buildparams = {
            "buildspec": self.get_buildspec(),
            "build_timeout": self.build_timeout
        }

        if self.build_env_vars:
            self.buildparams["build_env_vars"] = self.build_env_vars

        if self.compute_type:
            self.buildparams["compute_type"] = self.compute_type

        if self.image_type:
            self.buildparams["image_type"] = self.image_type

        if self.build_image:
            self.buildparams["build_image"] = self.build_image

        self._phase2complete_file = f"/var/tmp/share/{self.stateful_id}"
        self._set_phase2complete()

        return self.buildparams

    def run(self):
        self._setup()

        _set_env_vars = {
            "stateful_id": True,
            "tmp_bucket": True,
            "log_bucket": True,
            "app_dir": True,
            "remote_stateful_bucket": None,
            "upload_bucket": True,
            "run_share_dir": None,
            "share_dir": None
        }

        codebuild_helper = CodebuildResourceHelper(
            set_env_vars=_set_env_vars,
            **self.buildparams
        )

        if self._phase2complete("build_id") and self._phase2complete("status") is None:
            self.build_id = self._phase2complete["build_id"]
            self.logger.debug(f"check previous codebuild trigger {self.build_id} ...")
            codebuild_helper.retrieve(self.build_id,sparse_env_vars=True)
        else:
            self.logger.debug(f"trigger new codebuild ...")
            self._tar_upload_s3()
            codebuild_helper.run(sparse_env_vars=False)

        if codebuild_helper.results.get("output"):
            self.append_log(codebuild_helper.results["output"])
            del codebuild_helper.results["output"]

        os.remove(self._phase2complete_file)

        if codebuild_helper.results.get("status") is False:
            exit(9)

        exit(0)

if __name__ == "__main__":
    main = CodebuildSrcFile()
    main.run()
