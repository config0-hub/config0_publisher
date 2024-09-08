#!/usr/bin/env python

#from config0_publisher.fileutils import extract_tar_gz
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
        self.dl_subdir = kwargs.get("dl_subdir",'config0/downloads')

        if self.runtime_env == "lambda":
            self.bin_dir = f"/tmp/config0/bin"
        else:
            self.bin_dir = f"/usr/local/bin"

        self.execdir = f'{self.stateful_dir}/run/{self.app_dir}'  # notice the execution directory is in "run" subdir

        self.base_cmd = f'cd {self.execdir} && {self.bin_dir}/{self.binary}'

        self.base_file_path = f'{self.binary}_{self.version}_{self.arch}'
        self.bucket_path = f"s3://{self.bucket}/downloads/{self.app_name}/{self.base_file_path}"
        self.dl_file_path = f'$TMPDIR/{self.dl_subdir}/{self.base_file_path}'

        self.base_output_file = f'{self.stateful_dir}/output/{self.app_name}'
        self.base_generate_file = f'{self.stateful_dir}/generated/{self.app_name}'

    def _get_initial_preinstall_cmds(self):

        if self.runtime_env == "codebuild":
            cmds = [
                'which zip || apt-get update',
                'which zip || apt-get install -y unzip zip',
            ]
        else:
            cmds = [f'echo "downloading {self.base_file_path}"']

        return cmds

    def reset_dirs(self):

        cmds = [
            f'rm -rf $TMPDIR/config0 > /dev/null 2>&1 || echo "config0 already removed"',
            f'mkdir -p {self.stateful_dir}/run',
            f'mkdir -p {self.stateful_dir}/output/{self.app_name}',
            f'mkdir -p {self.stateful_dir}/generated/{self.app_name}',
            f'mkdir -p $TMPDIR/{self.dl_subdir}',
            f'echo "##############"; df -h; echo "##############"'
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

        # testtest456
        #_bucket_install = f'aws s3 cp {bucket_path} {dl_file_path} --quiet && echo "### GOT {base_file_path} from s3 bucket/cache"'
        #_src_install = f'curl -L -s {src_remote_path} -o {dl_file_path} && aws s3 cp {dl_file_path} {bucket_path} --quiet'

        _bucket_install = f'aws s3 cp {bucket_path} {dl_file_path} && echo "### GOT {base_file_path} from s3 bucket/cache"'
        _src_install = f'curl -L -s {src_remote_path} -o {dl_file_path} && aws s3 cp {dl_file_path} {bucket_path}'
        install_cmd = f'({_bucket_install}) || ({_src_install})'

        cmds = [ install_cmd ]
        cmds.append(f'mkdir -p {self.bin_dir} || echo "trouble making self.bin_dir {self.bin_dir}"')

        if self.installer_format == "zip":
            cmds.append(f'(cd $TMPDIR/{self.dl_subdir} && unzip {base_file_path} > /dev/null) || exit 0')
        elif self.installer_format == "targz":
            cmds.append(f'(cd $TMPDIR/{self.dl_subdir} && tar xfz {base_file_path} > /dev/null) || exit 0')

        return cmds