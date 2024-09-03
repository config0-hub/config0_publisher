#!/usr/bin/env python

#from config0_publisher.fileutils import extract_tar_gz

class TFAppHelper:

    def __init__(self,**kwargs):

        self.classname = "TFAppHelper"

        # required
        self.binary = kwargs['binary']
        self.version = kwargs['version']
        self.bucket = kwargs["bucket"]
        self.installer_format = kwargs.get("installer_format")
        self.src_remote_path = kwargs["src_remote_path"]

        # advisable
        self.runtime_env = kwargs.get("runtime_env",'codebuild')  # codebuild or lambda
        self.app_name = kwargs.get("app_name",self.binary)

        # pretty fixed
        self.stateful_dir = kwargs.get("stateful_dir",'$TMPDIR/config0/$STATEFUL_ID')
        self.tf_execdir = kwargs.get("tf_exedir",f'{self.stateful_dir}/run')  # notice the execution directory is in "run" subdir
        self.arch = kwargs.get("arch",'linux_amd64')
        self.dl_subdir = kwargs.get("dl_subdir",'config0/downloads')

        if self.runtime_env == "lambda":
            self.path_dir = f"/tmp/config0/bin"
        else:
            self.path_dir = f"/usr/local/bin"

        self.base_file_path = f'{self.binary}_{self.version}_{self.arch}'
        self.bucket_path = f"s3://{self.bucket}/downloads/{self.app_name}/{self.base_file_path}"
        self.dl_file_path = f'$TMPDIR/{self.dl_subdir}/{self.base_file_path}'

    def _get_initial_preinstall_cmds(self):

        if self.runtime_env == "codebuild":
            cmds = [
                'which zip || apt-get update',
                'which zip || apt-get install -y unzip zip',
            ]
        else:
            cmds = [f'echo "downloading {self.base_file_path}"']

        return cmds

    def download_cmds(self):

        cmds = self._get_initial_preinstall_cmds()

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
        else:
            base_file_path = f'{self.base_file_path}.{_suffix}'
            dl_file_path = f'{self.dl_file_path}.{_suffix}'
            bucket_path = f'{self.bucket_path}.{_suffix}'

        #_bucket_install = f'([ ! -f "{dl_file_path}" ] && aws s3 cp {bucket_path} {dl_file_path} --quiet && echo "### got {base_file_path} from s3 bucket/cache ###" )'
        #_src_install = f'echo "### getting {base_file_path} from source ###" && curl -L -s {self.src_remote_path} -o {dl_file_path} && aws s3 cp {dl_file_path} {bucket_path} --quiet'
        #install_cmd = f'({_bucket_install}) || ({_src_install})'
        # testtest456
        install_cmd = f'aws s3 cp {bucket_path} {dl_file_path}'
        install_cmd = f'aws s3 cp {bucket_path} {dl_file_path} && echo "### got {base_file_path} from s3 bucket/cache ###"'
        # testtest456

        cmds.append(install_cmd)
        cmds.append(f'mkdir -p {self.path_dir} || echo "trouble making self.path_dir {self.path_dir}"')

        if self.installer_format == "zip":
            cmds.append(f'(cd $TMPDIR/{self.dl_subdir} && unzip {base_file_path} > /dev/null) || exit 0')
        elif self.installer_format == "targz":
            cmds.append(f'(cd $TMPDIR/{self.dl_subdir} && tar xfz {base_file_path} > /dev/null) || exit 0')

        return cmds

