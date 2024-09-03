#!/usr/bin/env python

from config0_publisher.resource.common import TFAppHelper

class TFSecHelper(TFAppHelper):

    def __init__(self,**kwargs):

        self.classname = "TFSecHelper"

        binary = 'tfsec'
        version = kwargs.get("version","1.28.10")
        arch = kwargs.get("arch","linux_amd64")

        src_remote_path = f'https://github.com/aquasecurity/{binary}/releases/download/v{version}/{binary}-{arch}'.replace("_","-")  # tfsec uses hythen

        TFAppHelper.__init__(self,
                             binary=binary,
                             version=version,
                             arch=arch,
                             bucket=kwargs["tmp_bucket"],
                             runtime_env=kwargs["runtime_env"],
                             src_remote_path=src_remote_path)

    def install_cmds(self):

        cmds = self.download_cmds()
        cmds.append(f'(mv {self.dl_file_path} {self.path_dir}/{self.binary} > /dev/null) || exit 0')
        cmds.append(f'chmod 777 {self.path_dir}/{self.binary}')

        return cmds

    def exec_cmds(self):

        return [
            f'(cd {self.tf_execdir} && {self.path_dir}/{self.binary} --no-color > {self.stateful_dir}/output/{self.app_name}.log) || cat {self.stateful_dir}/output/{self.app_name}.log',
            f'(cd {self.tf_execdir} && {self.path_dir}/{self.binary} --no-color --format json > {self.stateful_dir}/output/{self.app_name}.json || echo "tfsec format json failed"'
        ]

        return cmds

    def get_all_cmds(self):

        cmds = self.install_cmds()
        cmds.extend(self.exec_cmds())

        return cmds