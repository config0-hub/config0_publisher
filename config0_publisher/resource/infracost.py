#!/usr/bin/env python
import os

from config0_publisher.resource.common import TFAppHelper

class TFInfracostHelper(TFAppHelper):

    def __init__(self,**kwargs):

        self.classname = "TFInfracostHelper"

        binary = 'infracost'
        version = kwargs.get("version","0.10.39")
        arch = kwargs.get("arch","linux_amd64")

        src_remote_path = f'https://github.com/infracost/{binary}/releases/download/v{version}/{binary}-{arch}'.replace("_","-")  # tfsec uses hythen

        TFAppHelper.__init__(self,
                             binary=binary,
                             version=version,
                             arch=arch,
                             bucket=kwargs["tmp_bucket"],
                             installer_format="targz",
                             runtime_env=kwargs["runtime_env"],
                             src_remote_path=src_remote_path)

    def install_cmds(self):

        #infracost-linux-amd64.tar.gz
        dl_file = f'{self.binary}-{self.arch}'.replace("_","-")

        cmds = self.download_cmds()
        cmds.append(f'(cd $TMPDIR/{self.dl_subdir} && mv {dl_file} {self.path_dir}/{self.binary} > /dev/null) || exit 0')
        cmds.append(f'chmod 777 {self.path_dir}/{self.binary}')

        return cmds

    def exec_cmds(self):

        return [
            f'cd {self.tf_execdir}; {self.path_dir}/{self.binary} breakdown --path . --out-file {self.app_name}.json --format json --out-file {self.stateful_dir}/output/{self.app_name}.json',
            f'cd {self.tf_execdir}; {self.path_dir}/{self.binary} --no-color breakdown --path . > {self.stateful_dir}/output/{self.app_name}.log',
            f'find {self.stateful_dir}'  # testtest456
            ]

        return cmds

    def get_all_cmds(self):

        if not os.environ.get("INFRACOST_API_KEY"):
            return []

        cmds = self.install_cmds()
        cmds.extend(self.exec_cmds())

        return cmds