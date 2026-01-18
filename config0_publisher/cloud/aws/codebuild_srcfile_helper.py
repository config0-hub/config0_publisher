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

    def get_buildspec(self):
        self.logger.info("DEBUG: get_buildspec() called - starting buildspec processing")
        
        # get with provided b64 hash
        if self.buildspec_hash:
            self.logger.info("DEBUG: Using buildspec from buildspec_hash")
            buildspec_content = b64_decode(self.buildspec_hash)
        else:
            # get repo file and read contents
            buildspec_file = os.path.join(
                self._get_fqn_app_dir_path(),
                "src",
                self.buildspec_file
            )
            self.logger.info(f"DEBUG: Reading buildspec from file: {buildspec_file}")
            with open(buildspec_file, "r") as file:
                buildspec_content = file.read()

        self.logger.info(f"DEBUG: Original buildspec length: {len(buildspec_content)} characters")
        self.logger.info(f"DEBUG: Original buildspec first 500 chars:\n{buildspec_content[:500]}")

        # Ensure done file is written in post_build phase for async tracking
        buildspec_content = self._ensure_done_file_write(buildspec_content)

        self.logger.info(f"DEBUG: Modified buildspec length: {len(buildspec_content)} characters")
        self.logger.info(f"DEBUG: Modified buildspec first 500 chars:\n{buildspec_content[:500]}")
        
        # Check if on-failure: CONTINUE was added
        if 'on-failure: CONTINUE' in buildspec_content:
            self.logger.info("DEBUG: ✓ on-failure: CONTINUE found in buildspec")
        else:
            self.logger.warn("DEBUG: ✗ on-failure: CONTINUE NOT found in buildspec")
        
        # Check if done file write was added
        if 'executions/${EXECUTION_ID}/done' in buildspec_content or 'executions/$EXECUTION_ID/done' in buildspec_content:
            self.logger.info("DEBUG: ✓ done file write found in buildspec")
        else:
            self.logger.warn("DEBUG: ✗ done file write NOT found in buildspec")

        return buildspec_content

    def _ensure_done_file_write(self, buildspec_content):
        """
        Ensure the buildspec includes post_build phase that writes the done file to S3.
        This is required for async execution tracking to detect build completion.
        The done file is written even if the build fails, allowing proper async tracking.
        """
        import re
        
        self.logger.info("DEBUG: _ensure_done_file_write() called - checking buildspec")
        
        # Check if done file write already exists (normalize $ and ${ for matching)
        normalized_content = buildspec_content.replace('${', '$VAR{').replace('{', '$VAR{')
        done_file_patterns = [
            "executions/$VAR{EXECUTION_ID}/done",
            "executions/.*?/done",
            "s3://.*?/executions/.*?/done"
        ]
        
        has_done_file_write = any(re.search(pattern, normalized_content, re.IGNORECASE) for pattern in done_file_patterns)

        # If done file write already exists, return as-is
        if has_done_file_write:
            self.logger.info("DEBUG: Buildspec already contains done file write command - skipping injection")
            return buildspec_content
        
        self.logger.info("DEBUG: Done file write not found - will inject it")

        # Check if post_build phase exists
        has_post_build = re.search(r'^\s*post_build:', buildspec_content, re.MULTILINE) or re.search(r'^\s*post-build:', buildspec_content, re.MULTILINE)

        # Done file write commands using environment variable placeholders
        # Use ${OUTPUT_BUCKET} and ${EXECUTION_ID} which will be resolved in CodeBuild environment
        # Write done file in post_build phase (runs after build phase completes, regardless of success/failure)
        # Note: post_build runs even if build fails, but NOT if pre_build fails (unless pre_build has on-failure: CONTINUE)
        done_file_commands = '''  post_build:
    commands:
      - date +%s > done || echo "$(date +%s)" > done
      - echo "Uploading done file to S3..."
      - aws s3 cp done s3://${OUTPUT_BUCKET}/executions/${EXECUTION_ID}/done || true
'''
        
        # Ensure pre_build has on-failure: CONTINUE so post_build runs even if pre_build fails
        # This matches the pattern used in codebuild.py (line 133) to ensure done file is written
        # CodeBuild runs each phase in a separate shell, so traps don't persist across phases
        # Also remove/replace 'when: onSuccess' if present, as it may not be recognized in all contexts
        pre_build_match = re.search(r'^\s*pre_build:', buildspec_content, re.MULTILINE)
        if pre_build_match:
            self.logger.info(f"DEBUG: Found pre_build: at position {pre_build_match.start()}")
            # Find where commands: appears after pre_build: (within next 200 chars to avoid matching wrong section)
            pre_build_start = pre_build_match.start()
            search_end = min(pre_build_start + 200, len(buildspec_content))
            section_after_pre_build = buildspec_content[pre_build_start:search_end]
            
            self.logger.info(f"DEBUG: Section after pre_build (first 300 chars):\n{section_after_pre_build[:300]}")
            
            # Check if on-failure is already in this section
            if 'on-failure:' not in section_after_pre_build:
                self.logger.info("DEBUG: on-failure: not found in pre_build - will add it")
                # Find the end of the pre_build: line
                pre_build_line_end = buildspec_content.find('\n', pre_build_start)
                if pre_build_line_end > 0:
                    # Determine indentation by checking the first line after pre_build:
                    # Look for next non-empty line to determine indentation level
                    next_lines = buildspec_content[pre_build_line_end + 1:pre_build_line_end + 50]
                    indent_match = re.search(r'^(\s+)', next_lines, re.MULTILINE)
                    if indent_match:
                        indent = indent_match.group(1)
                        self.logger.info(f"DEBUG: Detected indentation: '{indent}' (length: {len(indent)})")
                    else:
                        indent = '    '  # Default to 4 spaces if can't determine
                        self.logger.info(f"DEBUG: Using default indentation: '{indent}' (length: {len(indent)})")
                    
                    # Check if 'when: onSuccess' is present - if so, replace it with on-failure: CONTINUE
                    # Otherwise, insert on-failure: CONTINUE after pre_build: line
                    when_match = re.search(r'^(\s+)when:\s*onSuccess\s*$', next_lines, re.MULTILINE)
                    if when_match:
                        # Replace 'when: onSuccess' with 'on-failure: CONTINUE'
                        when_line_pos = pre_build_line_end + 1 + when_match.start()
                        when_line_end = buildspec_content.find('\n', when_line_pos)
                        if when_line_end > 0:
                            buildspec_content = buildspec_content[:when_line_pos] + f'{indent}on-failure: CONTINUE\n' + buildspec_content[when_line_end + 1:]
                            self.logger.info(f"DEBUG: ✓ Replaced 'when: onSuccess' with 'on-failure: CONTINUE' in pre_build")
                        else:
                            # Fallback: insert on-failure after pre_build line
                            on_failure_line = f'{indent}on-failure: CONTINUE\n'
                            buildspec_content = buildspec_content[:pre_build_line_end + 1] + on_failure_line + buildspec_content[pre_build_line_end + 1:]
                            self.logger.info(f"DEBUG: ✓ Added on-failure: CONTINUE to pre_build phase")
                    else:
                        # Insert on-failure: CONTINUE on new line after pre_build:
                        on_failure_line = f'{indent}on-failure: CONTINUE\n'
                        self.logger.info(f"DEBUG: Inserting line: '{on_failure_line.rstrip()}' after pre_build:")
                        buildspec_content = buildspec_content[:pre_build_line_end + 1] + on_failure_line + buildspec_content[pre_build_line_end + 1:]
                        self.logger.info("DEBUG: ✓ Added on-failure: CONTINUE to pre_build phase")
                else:
                    self.logger.warn("DEBUG: Could not find newline after pre_build:")
            else:
                self.logger.info("DEBUG: on-failure: already present in pre_build - skipping")
        else:
            self.logger.warn("DEBUG: pre_build: phase not found in buildspec")
        
        # Add a debug command in install phase to verify buildspec is being used
        # This will appear in CodeBuild logs and prove our modifications are applied
        install_match = re.search(r'^\s*install:\s*', buildspec_content, re.MULTILINE)
        if install_match:
            install_start = install_match.start()
            commands_pos = buildspec_content.find('commands:', install_start, install_start + 100)
            if commands_pos > 0:
                commands_line_end = buildspec_content.find('\n', commands_pos)
                if commands_line_end > 0:
                    debug_command = '      - echo "DEBUG: Buildspec modified by codebuild_srcfile_helper.py - on-failure: CONTINUE should be in pre_build"\n'
                    buildspec_content = buildspec_content[:commands_line_end + 1] + debug_command + buildspec_content[commands_line_end + 1:]
                    self.logger.info("DEBUG: ✓ Added debug command to install phase")

        if has_post_build:
            # If post_build exists, append the done file write command to it
            # Find the end of post_build commands section (before next phase or end of phases)
            # Match post_build section until next phase or end
            pattern = r'(post_build:\s*commands:\s*(?:^\s+-.*?\n)+?)(?=\n\s*\w+:|$)'
            match = re.search(pattern, buildspec_content, re.MULTILINE)
            if match:
                # Append done file commands to existing post_build commands
                existing_commands = match.group(1).rstrip()
                done_commands_to_add = '''      - date +%s > done || echo "$(date +%s)" > done
      - echo "Uploading done file to S3..."
      - aws s3 cp done s3://${OUTPUT_BUCKET}/executions/${EXECUTION_ID}/done || true
'''
                replacement = existing_commands + "\n" + done_commands_to_add
                buildspec_content = buildspec_content[:match.start()] + replacement + buildspec_content[match.end():]
            else:
                # Fallback: append at end of file if pattern doesn't match
                buildspec_content = buildspec_content.rstrip() + "\n" + done_file_commands
        else:
            # If post_build doesn't exist, append it at the end
            buildspec_content = buildspec_content.rstrip() + "\n" + done_file_commands

        self.logger.info("Injected done file write into buildspec post_build phase (runs on both success and failure)")
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
        self.logger.debug(f"trigger new codebuild ...")
        self._tar_upload_s3()

        # Get CodeBuild invocation config via pre_trigger
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
                if results.get("status") and results["status"].get("build_id"):
                    codebuild_helper.retrieve(build_id=results["status"]["build_id"], sparse_env_vars=True)
                    results = codebuild_helper.results
                    results["done"] = True
                    results["async_mode"] = True
                
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
            
            return results

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
