#!/usr/bin/env python
#
#Project: config0_publisher: Config0 is a SaaS for building and managing
#software and DevOps automation. This particular packages is a python
#helper for publishing stacks, hostgroups, shellouts/scripts and other
#assets used for automation
#
#Examples include cloud infrastructure, CI/CD, and data analytics
#
#Copyright (C) Gary Leong - All Rights Reserved
#Unauthorized copying of this file, via any medium is strictly prohibited
#Proprietary and confidential
#Written by Gary Leong  <gary@config0.com, May 11,2020

import os
import json
from time import sleep

from config0_publisher.loggerly import Config0Logger
from config0_publisher.utilities import OnDiskTmpDir
from config0_publisher.resource_manage import ResourceCmdHelper
from config0_publisher.utilities import id_generator


class GcloudCli(ResourceCmdHelper):

    def __init__(self,**kwargs):

        ResourceCmdHelper.__init__(self,
                                   app_name="gcloudcli")

        self.classname = 'GcloudCli'
        self.logger = Config0Logger(self.classname)
        self.logger.debug("Instantiating %s" % self.classname)
        self.file_config = None
        self.file_config_loc = None
        self.tempdir = None
        self.resource_tags_keys = [ "tags", 
                                    "name", 
                                    "schedule_id", 
                                    "job_instance_id",
                                    "job_id" ]

        self.share_dir = os.environ.get("SHARE_DIR","/var/tmp/share")

        self.stateful_dir = os.path.join(self.share_dir,
                                         id_generator(8))

        self.docker_image = "google/cloud-sdk"
        self.output = []

    def get_tags(self):

        tags = [ self.gcloud_region, 
                 self.product, 
                 self.provider ]

        for key_eval in self.resource_tags_keys:
            if not self.inputargs.get(key_eval): continue
            tags.append(self.inputargs[key_eval])

        return tags

    def set_ondisktmp(self):
        self.tempdir = OnDiskTmpDir()

    def write_file_config(self):

        with open(self.file_config_loc, 'w') as _file:
            _file.write(json.dumps(self.file_config,indent=4))

    def parse_set_env_vars(self,env_vars,upper_case=True):

        self.inputargs = {}

        for env_var in env_vars:

            if not os.environ.get(env_var.upper()):
                continue

            if env_var == "gcloud_region":
                self.inputargs["gcloud_region"] = os.environ[env_var.upper()]
            else:
                self.inputargs[env_var] = os.environ[env_var.upper()]

    def get_resource_tags(self,**kwargs):

        name = kwargs.get("name")
        if not name: name = self.inputargs.get("name")
        
        tags = "["

        if name: 
            tags = tags + "{"+"Key={},Value={}".format("Name",name)+"}"
        
        for key_eval in self.resource_tags_keys:

            if not self.inputargs.get(key_eval): 
                continue

            tags = tags + ",{"+"Key={},Value={}".format(key_eval,self.inputargs[key_eval])+"}"

        tags = tags + "]"

        return tags

    def get_region(self):

        self.gcloud_region = self.inputargs.get("gcloud_region")

        if not self.gcloud_region or self.gcloud_region == "None": 
            self.gcloud_region = "us-west1"

        self.logger.debug('Region set to "{}"'.format(self.gcloud_region))

    #################################################################################################################
    # non docker execution

    def _get_init_credentials_cmds(self):

        self.set_required()
        cmds = [ "gcloud auth activate-service-account --key-file={}".format(self.google_application_credentials) ]
        cmds.append("gcloud config set project {}".format(self.gcloud_project))

        return cmds

    def set_credentials(self):

        cmds = self._get_init_credentials_cmds()

        for cmd in cmds:
            results = self.execute(cmd,output_to_json=None,exit_error=True)
            output = results.get("output")
            if output: self.logger.debug(output)

            self.add_output(cmd=cmd,remove_empty=True,**results)

    #################################################################################################################
    # docker execution

    def cleanup_docker_run(self):

        if hasattr(self,"gcloud_container_name") and self.gcloud_container_name:
            cmd = [ "docker rm -fv {} 2>&1 > /dev/null".format(self.gcloud_container_name) ]
            self.execute(cmd,exit_error=False,output_to_json=None)

        if hasattr(self,"filename") and self.filename:
            os.system("rm -rf {}".format(self.filename))

        if hasattr(self,"tempdir") and self.tempdir: 
            self.tempdir.delete()

    def init_docker_run(self):

        self.gcloud_container_name = id_generator(8)

        cmds = ["docker pull {}:latest 2>&1 > /dev/null".format(self.docker_image)]
        cmds.append('for i in `docker ps -a|grep gcloud| cut -d " " -f 1`; do echo $i; docker rm -fv $i; done')

        cmds.append("docker run -v {}:{} --name {} {} gcloud auth activate-service-account --key-file {} || exit 4".format(self.google_application_credentials,
                                                                                                                           self.google_application_credentials,
                                                                                                                           self.gcloud_container_name,
                                                                                                                           self.docker_image,
                                                                                                                           self.google_application_credentials))

        cmds.append("docker run --rm --volumes-from {} {} gcloud config set project {}".format(self.gcloud_container_name,
                                                                                               self.docker_image,
                                                                                               self.gcloud_project))

        for cmd in cmds:

            results = self.execute(cmd,output_to_json=None,exit_error=False)
            status = results.get("status")
            output = results.get("output")
            if output: self.logger.debug(output)
  
            self.add_output(cmd=cmd,remove_empty=True,**results)

            if not status: return False

        return True

    def write_cloud_creds(self):
    
        project_id = os.environ.get("GCLOUD_PROJECT")
        private_key_id = os.environ.get("GCLOUD_PRIVATE_KEY_ID")
        private_key = os.environ.get("GCLOUD_PRIVATE_KEY")
        client_id = os.environ.get("GCLOUD_CLIENT_ID")
        client_email = os.environ.get("GCLOUD_CLIENT_EMAIL")
        client_x509_cert_url = os.environ.get("GCLOUD_CLIENT_X509_CERT_URL")
    
        if not project_id: 
            self.logger.debug("GCLOUD_PROJECT is required for write credentials")
            return
    
        if not private_key_id: 
            self.logger.debug("GCLOUD_PRIVATE_KEY_ID is required for write credentials")
            return
    
        if not private_key: 
            self.logger.debug("GCLOUD_PRIVATE_KEY is required for write credentials")
            return
    
        if not client_id: 
            self.logger.debug("GCLOUD_CLIENT_ID is required for write credentials")
            return
    
        if not client_email: 
            self.logger.debug("GCLOUD_CLIENT_EMAIL is required for write credentials")
            return
    
        if not client_x509_cert_url: 
            self.logger.debug("GCLOUD_CLIENT_X509_CERT_URL is required for write credentials")
            return
    
        if not hasattr(self,"tempdir") or not self.tempdir:
            self.set_ondisktmp()

        self.google_application_credentials = os.path.join(self.stateful_dir,".creds","gcloud.json")

        creds_dir = os.path.dirname(self.google_application_credentials)
    
        auth_uri = os.environ.get("GCLOUD_AUTH_URI","https://accounts.google.com/o/oauth2/auth")
        token_uri = os.environ.get("GCLOUD_TOKEN_URI","https://oauth2.googleapis.com/token")
        auth_provider = os.environ.get("GCLOUD_AUTH_PROVIDER","https://www.googleapis.com/oauth2/v1/certs")
    
        values = { "type": "service_account",
                   "auth_uri": auth_uri,
                   "token_uri": token_uri,
                   "auth_provider_x509_cert_url": auth_provider,
                   "project_id": project_id,
                   "private_key_id": private_key_id,
                   "private_key": private_key,
                   "client_email": client_email,
                   "client_id": client_id,
                   "client_x509_cert_url": client_x509_cert_url,
                   }
    
        json_object = json.dumps(values,indent=2).replace('\\\\','\\')
    
        if not os.path.exists(creds_dir):
            os.system("mkdir -p {}".format(creds_dir))
          
        self.logger.debug("gcloud directory {} ...".format(self.google_application_credentials))
    
        # Writing to sample.json 
        with open(self.google_application_credentials, "w") as outfile: 
            outfile.write(json_object) 

        return self.google_application_credentials

    def set_required(self):

        self.google_application_credentials = self.write_cloud_creds()

        if not self.google_application_credentials:
            self.google_application_credentials = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")

        if not self.google_application_credentials:
            self.logger.error('cannot find environmental variables "GOOGLE_APPLICATION_CREDENTIALS"')
            exit(4)

        self.gcloud_project = os.environ.get("GCLOUD_PROJECT")

        if not self.gcloud_project:
            self.logger.error('cannot find environmental variables "GCLOUD_PROJECT"')
            exit(4)

        return True
