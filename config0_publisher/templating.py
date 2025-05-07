#!/usr/bin/env python
#

import os
import re


def list_template_files(rootdir, split_dir=None):
    """
    Lists and categorizes template files with .ja2 extension from a directory.
    
    Args:
        rootdir: Root directory to search for template files
        split_dir: Directory name to split paths on, defaults to basename of rootdir
        
    Returns:
        List of dictionaries containing file metadata or None if rootdir doesn't exist
    """
    if not split_dir:
        try:
            split_dir = os.path.basename(rootdir)
        except Exception as e:
            split_dir = "_ed_templates"
            
    if not os.path.exists(rootdir):
        return None

    # Get all base files
    base_files = []
    try:
        for root, _, files in os.walk(rootdir):
            temp_list = []
            
            for file in files:
                f = os.path.join(root, file)
                temp_list.append(f)
                
            if not temp_list:
                continue
                
            for file in temp_list:
                if not re.search(r"\.ja2$", file):
                    continue
                base_files.append(file)
    except Exception as e:
        return None

    # Categorize files
    file_list = []
    for file in base_files:
        try:
            rel_file = file.split(f"{split_dir}/")[-1]
            filename = os.path.basename(rel_file)
            
            try:
                directory = os.path.dirname(rel_file)
            except Exception:
                directory = None
                
            finput = {
                "file": file,
                "filename": filename,
                "directory": directory
            }
            
            file_list.append(finput)
        except Exception:
            # Skip files that cause errors during processing
            continue
            
    return file_list