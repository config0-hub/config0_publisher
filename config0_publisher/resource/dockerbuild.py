#!/usr/bin/env python

import os
from config0_publisher.loggerly import Config0Logger
from config0_publisher.shellouts import execute3

class DockerLocalBuild(object):

    def __init__(self,**kwargs):

        '''
        this is meant to be inherit and not
        to be run standalone
        '''

        self.classname = "DockerLocalBuild"

        self.logger = Config0Logger(self.classname,
                                    logcategory="cloudprovider")

        self.build_env_vars = kwargs["build_env_vars"]
        self.docker_env_file = kwargs["docker_env_file"]
        self.share_dir = kwargs["share_dir"]
        self.run_share_dir = kwargs["run_share_dir"]
        self.method = kwargs["method"]
        self.docker_image = kwargs["docker_image"]

    def _create_docker_env_file(self):

        # note: self.docker_env_file is set by
        # "_get_docker_env_filepath" in ResourceCmdHelper
        if not self.build_env_vars.items():
            return

        file_obj = open(self.docker_env_file,"w")

        for _k,_v in self.build_env_vars.items():
            file_obj.write("\n")
            file_obj.write("{}={}".format(_k,_v))

        file_obj.close()

    def _get_docker_run_cmd(self,**kwargs):

        share_dir = kwargs.get("share_dir",
                               self.share_dir)

        run_share_dir = kwargs.get("run_share_dir",
                                   self.run_share_dir)

        docker_env_file = kwargs.get("docker_env_file",
                                     self.docker_env_file)

        if not os.path.exists(docker_env_file):

            self.logger.error("Cannot find environmental file {}".format(docker_env_file))

            if self.method:
                cmd = 'docker run -e METHOD="{}" --rm -v {}:{} {}'.format(self.method,
                                                                          run_share_dir,
                                                                          share_dir,
                                                                          self.docker_image)
            else:
                cmd = 'docker run --rm -v {}:{} {}'.format(run_share_dir,
                                                           share_dir,
                                                           self.docker_image)
        else:
            if self.method:
                cmd = 'docker run -e METHOD="{}" --env-file {} --rm -v {}:{} {}'.format(self.method,
                                                                                        docker_env_file,
                                                                                        run_share_dir,
                                                                                        share_dir,
                                                                                        self.docker_image)
            else:
                cmd = 'docker run --env-file {} --rm -v {}:{} {}'.format(docker_env_file,
                                                                         run_share_dir,
                                                                         share_dir,
                                                                         self.docker_image)

        return cmd

    def _aggregate_output(self,results,output=None):

        if not output:
            output = ""

        if not results:
            return output

        try:
            _output = results.get("output")
        except Exception:
            _output = None

        if not _output:
            return output

        return output + results.get("output")

    def run(self,retries=None):

        self._create_docker_env_file()

        os.chdir(self.run_share_dir)
        cmd = self._get_docker_run_cmd()
        self.logger.debug(cmd)

        if self.method == "destroy" and retries:
            retries = 6

        if not retries:
            retries = 1

        output = None
        results = {}

        for retry in range(retries):

            results = execute3(cmd,
                               output_to_json=False,
                               exit_error=False)

            output = self._aggregate_output(results,
                                            output=output)

            if not results or results.get("status") is False:
                continue

            break

        results["output"] = output

        return results