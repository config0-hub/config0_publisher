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
        cmds.append(f'(mv {self.dl_file_path} {self.bin_dir}/{self.binary} > /dev/null) || exit 0')
        cmds.append(f'chmod 777 {self.bin_dir}/{self.binary}')

        return cmds

    def exec_cmds(self):

        return [
            f'({self.base_cmd} --no-color --out {self.tmp_base_output_file}.out) || echo "tfsec check failed"',
            f'({self.base_cmd} --no-color --format json --out {self.tmp_base_output_file}.json) || echo "tfsec check with json output failed"'
        ]

    def get_all_cmds(self):

        cmds = self.install_cmds()
        cmds.extend(self.exec_cmds())

        return cmds