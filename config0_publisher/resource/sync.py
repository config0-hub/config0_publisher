#!/usr/bin/env python

import subprocess
import os
import shutil
from pathlib import Path

class SyncToShare:
    """
    Main class for handling resource synchronization to shared location.
    Inherits functionality from ResourceCmdHelper.
    """

    def __init__(self):
        self.classname = 'SyncToShare'

    def rsync_to_share(self, rsync_args=None, exclude_existing=None):
        if not self.run_share_dir: 
            self.logger.debug("run_share_dir not defined - skipping sync-ing ...")
            return
            
        # Create destination directory if needed
        _dirname = os.path.dirname(self.run_share_dir)
        Path(_dirname).mkdir(parents=True, exist_ok=True)

        if not rsync_args:
            rsync_args = "-avug"

        if exclude_existing:
            rsync_args = f'{rsync_args} --ignore-existing '

        #rsync -h -v -r -P -t source target
        cmd = f"rsync {rsync_args} {self.exec_dir}/ {self.run_share_dir}"
        self.logger.debug(cmd)
        
        # Using subprocess to run rsync
        try:
            subprocess.run(["rsync"] + rsync_args.split() + [f"{self.exec_dir}/", f"{self.run_share_dir}"], 
                           check=True, capture_output=True, text=True)
            self.logger.debug(f"Sync-ed to run share dir {self.run_share_dir}")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Failed to sync to {self.run_share_dir}: {e.stderr}")
            exit(1)

    def sync_to_share(self, exclude_existing=None):
        if not self.run_share_dir:
            self.logger.debug("run_share_dir not defined - skipping sync-ing ...")
            return

        # Create destination directory if needed
        _dirname = os.path.dirname(self.run_share_dir)
        self._mkdir(_dirname)

        # Copy directory contents
        source_dir = Path(self.exec_dir)
        target_dir = Path(self.run_share_dir)

        for item in source_dir.glob('**/*'):
            if item.is_file():
                # Get the relative path
                relative_path = item.relative_to(source_dir)
                destination = target_dir / relative_path

                # Create parent directories if they don't exist
                destination.parent.mkdir(parents=True, exist_ok=True)

                # Skip existing files if exclude_existing is True
                if exclude_existing and destination.exists():
                    continue

                # Copy with metadata (timestamps, permissions)
                shutil.copy2(item, destination)

        self.logger.debug(f"Sync-ed to run share dir {self.run_share_dir}")