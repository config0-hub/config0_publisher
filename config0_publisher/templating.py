#!/usr/bin/env python
#

import os
import re

def list_template_files(rootdir, split_dir=None):

    if not split_dir: 
        try:
            split_dir = os.path.basename(rootdir)
        except:
            split_dir = "_ed_templates"

    if not os.path.exists(rootdir): return

    # get a base file lists
    base_files = []

    for root, subFolders, files in os.walk(rootdir):
        temp_list = []

        for file in files:
            f = os.path.join(root, file)
            temp_list.append(f)

        if not temp_list:
            continue

        for file in temp_list:
            if not re.search(".ja2$", file):
                continue
            base_files.append(file)

    # categorize files
    file_list = []

    for file in base_files:
        rel_file = file.split(f"{split_dir}/")[-1]

        filename = os.path.basename(rel_file)

        try:
            directory = os.path.dirname(rel_file)
        except:
            directory = None

        finput = { "file": file,
                    "filename": filename,
                    "directory": directory }

        file_list.append(finput)

    return file_list
