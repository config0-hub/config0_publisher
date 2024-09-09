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
        cmds.append(f'(cd $TMPDIR/{self.dl_subdir} && mv {dl_file} {self.bin_dir}/{self.binary} > /dev/null) || exit 0')
        cmds.append(f'chmod 777 {self.bin_dir}/{self.binary}')

        return cmds

    # infracost only executed in lambda
    def exec_cmds(self,src_env_file):

        cmds = [
            f'echo "executing INFRACOST"',
            f'({src_env_file} &&  {self.base_cmd} --no-color breakdown --path . --format json --out-file {self.tmp_base_output_file}.json) || (echo "WARNING: looks like INFRACOST failed")',
            f'({src_env_file} && {self.base_cmd} --no-color breakdown --path . --out-file {self.tmp_base_output_file}.out && cat {self.tmp_base_output_file}.out | tee -a /tmp/$STATEFUL_ID.log ) || (echo "WARNING: looks like INFRACOST failed")'
        ]

        cmds.extend(self.local_output_to_s3(suffix="json",last_apply=None))
        cmds.extend(self.local_output_to_s3(suffix="out",last_apply=None))

        return cmds

    def get_all_cmds(self,src_env_file):

        cmds = self.install_cmds()
        cmds.extend(self.exec_cmds(src_env_file))

        return cmds