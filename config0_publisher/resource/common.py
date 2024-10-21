#!/usr/bin/env python

#from config0_publisher.fileutils import extract_tar_gz
import os
from time import time
from config0_publisher.loggerly import Config0Logger

class TFAppHelper:

    def __init__(self,**kwargs):

        self.classname = "TFAppHelper"

        self.logger = Config0Logger(self.classname,
                                    logcategory="cloudprovider")

        # required
        self.binary = kwargs['binary']
        self.version = kwargs['version']

        # used except on terraform binary
        self.bucket = kwargs.get("bucket")
        self.installer_format = kwargs.get("installer_format")
        self.src_remote_path = kwargs.get("src_remote_path")
        self.start_time = str(time())

        # advisable
        self.runtime_env = kwargs.get("runtime_env",'codebuild')  # codebuild or lambda

        if not hasattr(self,"app_name"):
            self.app_name = kwargs.get("app_name",self.binary)

        # pretty fixed
        self.stateful_dir = '$TMPDIR/config0/$STATEFUL_ID'

        self.app_dir = kwargs.get("app_dir","var/tmp/terraform")
        self.arch = kwargs.get("arch",'linux_amd64')

        if self.runtime_env == "lambda":
            self.bin_dir = f"/tmp/config0/bin"
        else:
            self.bin_dir = f"/usr/local/bin"

        os.makedirs(self.bin_dir, exist_ok=True)

        self.exec_dir = f'{self.stateful_dir}/run/{self.app_dir}'  # notice the execution directory is in "run" subdir

        self.base_cmd = f'cd {self.exec_dir} && {self.bin_dir}/{self.binary} '

        self.base_file_path = f'{self.binary}_{self.version}_{self.arch}'
        self.bucket_path = f"s3://{self.bucket}/downloads/{self.app_name}/{self.base_file_path}"
        self.dl_file_path = f'$TMPDIR/{self.base_file_path}'

        self.tmp_base_output_file = f'/tmp/{self.app_name}.$STATEFUL_ID'
        self.base_output_file = f'{self.stateful_dir}/output/{self.app_name}.$STATEFUL_ID'

    def _get_initial_preinstall_cmds(self):

        if self.runtime_env == "codebuild":
            cmds = [
                {"apt-get update": 'which zip || apt-get update'},
                {"install zip": 'which zip || apt-get install -y unzip zip'}
            ]
        else:
            cmds = [ { f'download "{self.binary}:{self.version}"': f'echo "downloading {self.base_file_path}"' }]

        return cmds

    def reset_dirs(self):

        cmds = [
            {"reset_dirs - clean local config0 dir": f'rm -rf $TMPDIR/config0 > /dev/null 2>&1 || echo "config0 already removed"'},
            {"reset_dirs - mkdir local run": f'mkdir -p {self.stateful_dir}/run'},
            {"reset_dirs - mkdir local output": f'mkdir -p {self.stateful_dir}/output/{self.app_name}'},
            {"reset_dirs - mkdir local generated": f'mkdir -p {self.stateful_dir}/generated/{self.app_name}'},
            {"reset_dirs - output diskspace": f'echo "##############"; df -h; echo "##############"'}
        ]

        cmds.extend(self._get_initial_preinstall_cmds())

        return cmds

    def download_cmds(self):

        if self.installer_format == "zip":
            _suffix = "zip"
        elif self.installer_format == "targz":
            _suffix = "tar.gz"
        else:
            _suffix = None

        if not _suffix:
            base_file_path = self.base_file_path
            dl_file_path = self.dl_file_path
            bucket_path = self.bucket_path
            src_remote_path = self.src_remote_path
        else:
            base_file_path = f'{self.base_file_path}.{_suffix}'
            dl_file_path = f'{self.dl_file_path}.{_suffix}'
            bucket_path = f'{self.bucket_path}.{_suffix}'
            src_remote_path = f'{self.src_remote_path}.{_suffix}'

        _hash_delimiter = 'echo "{}"'.format("#"*32)

        _bucket_install_1 = f'aws s3 cp {bucket_path} {dl_file_path} --quiet'
        _bucket_install_2 = f'echo "# GOT {base_file_path} from s3 bucket/cache"'
        _src_install_1 = f'echo "# NEED to get {base_file_path} from source"'
        _src_install_2= f'curl -L -s {src_remote_path} -o {dl_file_path}'
        _src_install_3 = f'aws s3 cp {dl_file_path} {bucket_path} --quiet'

        _bucket_install = f'{_bucket_install_1} && {_hash_delimiter} && {_bucket_install_2} && {_hash_delimiter}'
        _src_install = f'{_hash_delimiter} && {_src_install_1} && {_hash_delimiter} && {_src_install_2} && {_src_install_3}'

        install_cmd = f'({_bucket_install}) || ({_src_install})'

        cmds = [
            {f'install cmd for {self.binary}': install_cmd },
            {'mkdir bin dir': f'mkdir -p {self.bin_dir} || echo "trouble making self.bin_dir {self.bin_dir}"'}
        ]

        if self.installer_format == "zip":
            cmds.append({ f'unzip downloaded "{self.binary}:{self.version}"': f'(cd $TMPDIR && unzip {base_file_path} > /dev/null) || exit 0'})
        elif self.installer_format == "targz":
            cmds.append({ f'untar downloaded "{self.binary}:{self.version}"': f'(cd $TMPDIR && tar xfz {base_file_path} > /dev/null) || exit 0'})

        return cmds

    def local_output_to_s3(self,srcfile=None,suffix=None,last_apply=None):

        if not srcfile and suffix:
            srcfile = f'{self.tmp_base_output_file}.{suffix}'

        if not srcfile:
            raise Exception("srcfile needs to be determined to upload to s3")

        _filename = os.path.basename(srcfile)

        base_cmd = f'aws s3 cp {srcfile} s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID'

        if last_apply:
            cmd = f'{base_cmd}/applied/{_filename} || echo "trouble uploading output file"'
        else:
            cmd = f'{base_cmd}/cur/{_filename} || echo "trouble uploading output file"'

        return [{f'last_output_to_s3 "{_filename}"':cmd}]

    def s3_file_to_local(self,dstfile=None,suffix=None,last_apply=None):

        if not dstfile and suffix:
            dstfile = f'{self.base_output_file}.{suffix}'

        if not dstfile:
            raise Exception("dstfile needs to be determined to upload to s3")

        _filename = os.path.basename(dstfile)

        if last_apply:
            cmd = f'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID/applied/{_filename} {dstfile}'
        else:
            cmd = f'aws s3 cp s3://$REMOTE_STATEFUL_BUCKET/$STATEFUL_ID/cur/{_filename} {dstfile}'

        return [ {f's3_file_to_local "{_filename}"':cmd }]
