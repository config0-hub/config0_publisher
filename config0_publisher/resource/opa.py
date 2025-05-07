#!/usr/bin/env python

from config0_publisher.resource.common import TFAppHelper


class TFOpaHelper(TFAppHelper):
    """Helper class for Open Policy Agent (OPA) application management."""

    def __init__(self, **kwargs):
        """Initialize OPA helper with appropriate configuration."""
        self.classname = "TFOpaHelper"

        binary = 'opa'
        version = kwargs.get("version", "0.68.0")
        arch = kwargs.get("arch", "linux_amd64")

        src_remote_path = f"https://github.com/open-policy-agent/{binary}/releases/download/v{version}/{binary}_{arch}_static"

        TFAppHelper.__init__(self,
                             binary=binary,
                             version=version,
                             arch=arch,
                             bucket=kwargs["tmp_bucket"],
                             runtime_env=kwargs["runtime_env"],
                             src_remote_path=src_remote_path)

    def install_cmds(self):
        """Generate commands for installing OPA binary."""
        try:
            cmds = self.download_cmds()
            cmds.append(f'(mv {self.dl_file_path} {self.bin_dir}/{self.binary} > /dev/null) || exit 0')
            cmds.append(f'chmod 777 {self.bin_dir}/{self.binary}')
            return cmds
        except Exception as e:
            raise Exception(f"Error generating install commands: {str(e)}")

    # TODO opa not yet supported
    # opa is quite specific
    @staticmethod
    def exec_cmds():
        """Generate execution commands for OPA (not yet implemented)."""
        # cmds tbd
        return []

    def get_all_cmds(self):
        """Combine install and execution commands."""
        try:
            cmds = self.install_cmds()
            cmds.extend(self.exec_cmds())
            return cmds
        except Exception as e:
            raise Exception(f"Error getting combined commands: {str(e)}")