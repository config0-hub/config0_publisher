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
from config0_publisher.resource.aws_executor import AWSAsyncExecutor
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

    def _get_execution_id(self):
        """
        Get execution_id following rmanage.py insert_execution_id() pattern.
        First check EXECUTION_ID env var, fallback to stateful_id with warning.
        """
        execution_id = os.environ.get("EXECUTION_ID")
        if not execution_id:
            if self.stateful_id:
                execution_id = self.stateful_id
                self.logger.warn("EXECUTION_ID env var not found, using stateful_id as execution_id")
            else:
                raise Exception("EXECUTION_ID env var not set and stateful_id is not available")
        else:
            self.logger.debug(f"Found EXECUTION_ID env var: {execution_id}")
        return execution_id

    def _get_resource_type_id(self):
        """
        Get resource_type and resource_id from env vars or use defaults.
        Returns tuple (resource_type, resource_id).
        """
        resource_type = os.environ.get("RESOURCE_TYPE")
        resource_id = os.environ.get("RESOURCE_ID")

        if not resource_type:
            self.logger.debug("RESOURCE_TYPE env var not set, using default 'codebuild_srcfile'")
            resource_type = "codebuild_srcfile"

        if not resource_id:
            resource_id = self.stateful_id
            self.logger.debug(f"RESOURCE_ID env var not set, using stateful_id {self.stateful_id} as resource_id")

        if not resource_id:
            raise Exception("RESOURCE_ID env var not set and stateful_id is not available")

        self.logger.debug(f"Found RESOURCE_ID env var: {resource_id}, RESOURCE_TYPE: {resource_type}")
        return resource_type, resource_id

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

    def _get_debug_buildspec(self):

        buildspec_content = [
            "version: 0.2",
            "phases:",
            "  install:",
            "    on-failure: CONTINUE",
            "    commands:",
            "      - echo \"Installing system dependencies...\"",
            "      - apt-get update && apt-get install -y zip",
            "",
            "  pre_build:",
            "    on-failure: CONTINUE",
            "    commands:",
            "      - aws s3 cp s3://$UPLOAD_BUCKET/${STATEFUL_ID}/state/src.${STATEFUL_ID}.zip /tmp/${STATEFUL_ID}.zip --quiet",
            "      - mkdir -p /var/tmp/share",
            "      - mkdir -p /var/tmp/share/${STATEFUL_ID}",
            "      - unzip -o /tmp/${STATEFUL_ID}.zip -d /var/tmp/share/${STATEFUL_ID}/",
            "      - rm -rf /tmp/${STATEFUL_ID}.zip",
            "",
            "  build:",
            "    commands:",
            "      - cd /var/tmp/share/${STATEFUL_ID}/",
            "      - chmod 755 docker-to-lambda.sh",
            "      - ./docker-to-lambda.sh",
            "",
            "  post_build:",
            "    commands:",
            "      - date +%s > done",
            "      - echo \"Uploading done to S3 bucket...\"",
            "      - aws s3 cp done s3://$TMP_BUCKET/executions/${EXECUTION_ID}/done",
        ]

        return "\n".join(buildspec_content)

    def get_buildspec(self):
        self.logger.info("DEBUG: get_buildspec() called - starting buildspec processing")
        
        # get with provided b64 hash
        if self.buildspec_hash:
            self.logger.info("Using buildspec from buildspec_hash")
            buildspec_content = b64_decode(self.buildspec_hash)
        else:
            # get repo file and read contents
            buildspec_file = os.path.join(
                self._get_fqn_app_dir_path(),
                "src",
                self.buildspec_file
            )
            self.logger.info(f"Reading buildspec from file: {buildspec_file}")
            with open(buildspec_file, "r") as file:
                buildspec_content = file.read()

        #buildspec_content = self._get_debug_buildspec()

        return buildspec_content

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
        
        # Set OUTPUT_BUCKET for done file write (used in buildspec post_build phase)
        self.build_env_vars["OUTPUT_BUCKET"] = self.tmp_bucket

        # Set upload bucket
        if self.remote_stateful_bucket:
            self.build_env_vars["UPLOAD_BUCKET"] = self.remote_stateful_bucket
        else:
            self.build_env_vars["UPLOAD_BUCKET"] = self.tmp_bucket

        if self.docker_image:
            self.build_env_vars["DOCKER_IMAGE"] = self.docker_image

    def _tar_upload_s3(self):
        abs_app_dir = self._get_fqn_app_dir_path()
        temp_filename = f'{id_generator2()}.zip'
        srcfile = pyzip(
            abs_app_dir,
            self.tmpdir,
            temp_filename,
            exit_error=True
        )

        blob_url = f's3://{self.buildparams["build_env_vars"]["UPLOAD_BUCKET"]}/{self.stateful_id}/state/src.{self.stateful_id}.zip'
        cmd = f'aws s3 cp {srcfile} {blob_url} --quiet'
        self.logger.debug(f"Uploading source files to {blob_url}...")

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

        return self.buildparams

    def run(self):
        self._setup()

        # Get execution_id and resource parameters
        execution_id = self._get_execution_id()
        resource_type, resource_id = self._get_resource_type_id()

        # Set EXECUTION_ID in environment for CodebuildResourceHelper
        # (it needs this from AWSCommonConn.__init__)
        os.environ["EXECUTION_ID"] = execution_id

        # Create AWS Async Executor with current settings
        executor = AWSAsyncExecutor(
            resource_type=resource_type,
            resource_id=resource_id,
            execution_id=execution_id,
            output_bucket=self.tmp_bucket,
            stateful_id=self.stateful_id,
            build_timeout=self.build_timeout,
            app_dir=self.app_dir,
            app_name=self.app_name,
            remote_stateful_bucket=getattr(self, 'remote_stateful_bucket', None)
        )

        # Prepare CodeBuild invocation config
        # We still need CodebuildResourceHelper to prepare the buildparams
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

        # Upload source files to S3 before triggering build
        self._tar_upload_s3()

        # Get CodeBuild invocation config via pre_trigger
        self.logger.debug(f"trigger new codebuild ...")
        inputargs = codebuild_helper.pre_trigger(sparse_env_vars=False)

        # Determine async_mode - check if EXECUTION_ID is set (indicates async tracking)
        async_mode = bool(os.environ.get("EXECUTION_ID"))

        # Use the unified execute method
        results = executor.execute(
            execution_type="codebuild",
            async_mode=async_mode,
            **inputargs
        )

        if async_mode:
            # Async mode: check if done or in_progress
            
            # Always refresh phases JSON file path from env var (ensures it's up-to-date)
            self.set_phases_json()
            
            # Validate CONFIG0_PHASES_JSON_FILE env var is set (primary source)
            if not os.environ.get("CONFIG0_PHASES_JSON_FILE"):
                self.logger.warn("CONFIG0_PHASES_JSON_FILE env var not set - phases file may not be writable")
            
            # Ensure config0_phases_json_file is set before writing
            if not hasattr(self, "config0_phases_json_file") or not self.config0_phases_json_file:
                self.logger.warn(f"config0_phases_json_file not set - cannot write phases file. CONFIG0_PHASES_JSON_FILE env var: {os.environ.get('CONFIG0_PHASES_JSON_FILE')}")
            
            if results.get("done"):
                # Handle done case: retrieve results and delete phases file
                #if results.get("status") and results["status"].get("build_id"):
                codebuild_helper.retrieve(build_id=results["status"]["build_id"], sparse_env_vars=True)
                results = codebuild_helper.results
                results["done"] = True
                results["async_mode"] = True

                # TODO: refactor to avoid duplication
                # Process output logs
                if results.get("output") and results.get("status") is False:
                    print(results["output"])

                # Delete phases file when done (cleanup)
                self.delete_phases_to_json_file()
            
            # Write phases file if phases present and not done (for parent process to read)
            if results.get("phases") and not results.get("done"):
                # Ensure init or in_progress is set for exit code 135 (phase2complete)
                if not results.get("init") and not results.get("in_progress"):
                    results["init"] = True
                self.logger.info(f"Writing phases file with init=True for exit code 135. phases file: {self.config0_phases_json_file}")
                self.write_phases_to_json_file(results)
                self.logger.info(f"Phases file written successfully. Results keys: {list(results.keys())}")
            else:
                self.logger.warn(f"Not writing phases file - phases={results.get('phases')}, done={results.get('done')}")
        else:
            # Sync mode: retrieve build results directly
            # This not async mode which is not recommended as it is long running
            # process where file descriptors may not be held open
            if results.get("build_id"):
                codebuild_helper.retrieve(build_id=results["build_id"], sparse_env_vars=True)
                results = codebuild_helper.results

        # Process output logs
        if results.get("output"):
            self.append_log(results["output"])
            del results["output"]

        # Check final status
        if results.get("status") is False:
            exit(9)

        exit(0)

if __name__ == "__main__":
    main = CodebuildSrcFileHelper()
    main.run()
