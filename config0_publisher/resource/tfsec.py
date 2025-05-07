#!/usr/bin/env python

from config0_publisher.resource.common import TFAppHelper

class TFSecHelper(TFAppHelper):
    """Helper class for TFSec application integration."""

    def __init__(self, **kwargs):
        """Initialize TFSecHelper with configuration parameters."""
        self.classname = "TFSecHelper"

        binary = 'tfsec'
        version = kwargs.get("version", "1.28.10")
        arch = kwargs.get("arch", "linux_amd64")

        # tfsec uses hyphen instead of underscore
        src_remote_path = f'https://github.com/aquasecurity/{binary}/releases/download/v{version}/{binary}-{arch.replace("_", "-")}'

        try:
            TFAppHelper.__init__(self,
                                binary=binary,
                                version=version,
                                arch=arch,
                                bucket=kwargs["tmp_bucket"],
                                runtime_env=kwargs["runtime_env"],
                                src_remote_path=src_remote_path)
        except KeyError as e:
            raise KeyError(f"Missing required parameter for TFSecHelper initialization: {e}")

    def install_cmds(self):
        """Generate commands to download and install the TFSec binary."""
        cmds = self.download_cmds()
        cmds.append(f'(mv {self.dl_file_path} {self.bin_dir}/{self.binary} > /dev/null) || exit 0')
        cmds.append(f'chmod 777 {self.bin_dir}/{self.binary}')

        return cmds

    def exec_cmds(self):
        """Generate commands to execute TFSec checks and save outputs."""
        cmds = [
            f'({self.base_cmd} --no-color --out {self.tmp_base_output_file}.out | tee -a /tmp/$STATEFUL_ID.log) || echo "tfsec check failed"',
            f'({self.base_cmd} --no-color --format json --out {self.tmp_base_output_file}.json) || echo "tfsec check with json output failed"'
        ]

        cmds.extend(self.local_output_to_s3(suffix="json", last_apply=None))
        cmds.extend(self.local_output_to_s3(suffix="out", last_apply=None))

        return cmds

    def get_all_cmds(self):
        """Generate all commands for installation and execution."""
        cmds = self.install_cmds()
        cmds.extend(self.exec_cmds())

        return cmds