#!/usr/bin/env python

import tarfile
import zipfile
import traceback
import os
from typing import List, Optional
import sys
import re
from time import time
from time import sleep

def zip_file(filename: str, srcfile: str = ".env", filedirectory: Optional[str] = None) -> None:
    """Zips a single file to a specified location."""
    pwd = os.getcwd()
    filedirectory = filedirectory or pwd

    try:
        dstfile = f"{filename}.zip"
        with zipfile.ZipFile(dstfile, mode='w') as zf:
            zf.write(srcfile)
        os.chdir(pwd)
        print(f"file zipped here {os.path.join(filedirectory, dstfile)}")
    except Exception as e:
        os.chdir(pwd)
        print(f"Error zipping file: {str(e)}")
        raise

def list_all_files(rootdir: str, ignores: List[str] = [".pyc$", ".swp$"]) -> List[str]:
    """Lists all files in a directory that don't match ignore patterns."""
    file_list = []
    if not os.path.exists(rootdir): 
        return file_list

    for root, subFolders, files in os.walk(rootdir):
        temp_list = []
        for file in files:
            f = os.path.join(root, file)
            temp_list.append(f)

        for d in subFolders:
            g = os.path.join(root, d)
            temp_list.append(g)

        if not temp_list:
            continue

        if not ignores:
            file_list.extend(temp_list)
            continue

        for file in temp_list:
            add = True
            for ignore in ignores:
                if re.search(ignore, file):
                    add = False
                    break
            if add: 
                file_list.append(file)
    return file_list

def count_files_targz(file_path: str) -> int:
    """Counts the number of files in a tar.gz archive."""
    count = 0
    try:
        with tarfile.open(file_path, 'r:gz') as tar:
            for member in tar.getmembers():
                if member.isfile():
                    count += 1
        return count
    except Exception as e:
        print(f"Error counting files in tar.gz: {str(e)}")
        return 0

def pyzip(src: str, dst: str, filename: str, exit_error: bool = True, raise_on_empty: bool = True) -> Optional[str]:
    """Zips a file or directory to a specified location."""
    if not filename.endswith('.zip'):
        filename += '.zip'
    
    zip_path = os.path.join(dst, filename)
    
    # Ensure destination directory exists
    try:
        os.makedirs(dst, exist_ok=True)
    except Exception as e:
        error_msg = f"ref 34534263246/pyzip: Failed to create destination directory: {str(e)}"
        print(error_msg)
        if exit_error:
            raise Exception(error_msg)
        return False
    
    if not os.path.exists(src):
        error_msg = f"ref 34534263246/pyzip: source {src} does not exist."
        print(f"{error_msg}\n")
        if exit_error:
            sys.exit(78)
        return False

    try:
        # Create a ZipFile object
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            files_added = 0
            # Check if src is a file or directory
            if os.path.isfile(src):
                # If src is a file, just add it to the zip
                arcname = os.path.basename(src)
                zipf.write(src, arcname)
                files_added += 1
            else:
                # Walk through the directory
                for root, _, files in os.walk(src):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Calculate path relative to src
                        arcname = os.path.relpath(file_path, src)
                        # Add file to zip
                        zipf.write(file_path, arcname)
                        files_added += 1
    except zipfile.BadZipFile as e:
        error_msg = f"ref 34534263246/pyzip: Bad zip file: {str(e)}"
        print(error_msg)
        if exit_error:
            raise Exception(error_msg)
        return False
    except PermissionError as e:
        error_msg = f"ref 34534263246/pyzip: Permission denied: {str(e)}"
        print(error_msg)
        if exit_error:
            raise Exception(error_msg)
        return False
    except Exception as e:
        error_msg = f"ref 34534263246/pyzip: zip-ing failed: {str(e)}"
        print(f"{error_msg}\n{traceback.format_exc()}")
        if exit_error:
            raise Exception(error_msg)
        return False
        
    # Check if zip file was created and is not empty
    if not os.path.exists(zip_path):
        error_msg = f"ref 34534263246/pyzip: zip file was not created at {zip_path}"
        print(error_msg)
        if exit_error:
            raise Exception(error_msg)
        return False
        
    # Check if the zip file is empty (either no files added or zero file size)
    if files_added == 0 or os.path.getsize(zip_path) == 0:
        warning_msg = f"WARNING: ref 34534263246/pyzip: The created zip file appears to be empty: {zip_path}"
        print(warning_msg)
        if raise_on_empty:
            error_msg = f"ref 34534263246/pyzip: Created zip file is empty: {zip_path}"
            raise Exception(error_msg)
        return False

    print(f"ref 34534263246/pyzip file successfully zipped here: {zip_path}")
    return zip_path

def pyunzip(directory: str, name: str, newlocation: str, exit_error: bool = True, raise_on_empty: bool = False) -> Optional[str]:
    """Unzips a file to a specified location."""
    # Determine the filename
    if "zip" in name:
        filename = name
    elif os.path.exists(os.path.join(directory, f"{name}.zip")):
        filename = f"{name}.zip"
    else:
        print(f"\n{name} is not in the correct .zip format!\n")
        if exit_error:
            sys.exit(78)
        return False
    
    # Full path to the zip file
    zip_path = os.path.join(directory, filename)
    
    # Check if the zip file exists
    if not os.path.exists(zip_path):
        error_message = f"FAILED: Zip file does not exist: {zip_path}"
        print(error_message)
        if exit_error:
            raise FileNotFoundError(error_message)
        return False
    
    # Check if the file is actually a zip file
    if not zipfile.is_zipfile(zip_path):
        error_message = f"FAILED: Not a valid zip file: {zip_path}"
        print(error_message)
        if exit_error:
            raise zipfile.BadZipFile(error_message)
        return False
    
    try:
        # Create the destination directory if it doesn't exist
        os.makedirs(newlocation, exist_ok=True)
        
        # Extract all files from the zip
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Check if the zip file is empty
            file_list = zip_ref.namelist()
            if not file_list:
                empty_message = f"Zip file is empty: {zip_path}"
                print(f"WARNING: {empty_message}")
                if raise_on_empty:
                    raise ValueError(empty_message)
            
            # Extract the files
            zip_ref.extractall(path=newlocation)
        
        return newlocation
    
    except zipfile.BadZipFile as e:
        failed_message = f"FAILED: Invalid zip file format {zip_path}: {str(e)}"
        print(failed_message)
        if not exit_error:
            return False
        raise Exception(failed_message)
    
    except PermissionError as e:
        failed_message = f"FAILED: Permission denied when extracting {zip_path} to {newlocation}: {str(e)}"
        print(failed_message)
        if not exit_error:
            return False
        raise Exception(failed_message)

    except ValueError as e:
        # This would catch the empty zip file error we raise above
        failed_message = f"FAILED: {str(e)}"
        print(failed_message)
        if not exit_error:
            return False
        raise Exception(failed_message)

    except Exception as e:
        failed_message = f"FAILED: Error extracting {zip_path} to {newlocation}: {str(e)}"
        print(failed_message)
        if not exit_error:
            return False
        raise Exception(failed_message)

def targz(srcdir: str, dstdir: str, filename: str, verbose: bool = True) -> str:
    """Tars and gzips a file or directory to a specified location."""
    flags = "cvf" if verbose else "cv"
    tarfile_path = f"{os.path.join(dstdir, filename)}.tar.gz"

    # Make sure destination directory exists
    try:
        os.makedirs(dstdir, exist_ok=True)
    except Exception as e:
        raise Exception(f"Failed to create destination directory: {str(e)}")

    if not os.path.exists(srcdir):
        raise Exception(f"Source {srcdir} does not exist.\n")

    cmd = f"cd {srcdir}; tar {flags} - . | gzip -n > {tarfile_path}"
    exit_status = os.system(cmd)
    if int(exit_status) != 0:
        raise Exception(f"{cmd} failed")

    count = count_files_targz(tarfile_path)

    if count == 0:
        raise Exception("targz with zero files!")

    return tarfile_path

def un_targz(directory: str, name: str, newlocation: str, striplevel: Optional[int] = None) -> str:
    """Untars a tar.gz file to a specified location."""
    if "tar.gz" in name or "tgz" in name:
        filename = name
    elif os.path.exists(f"{directory}/{name}.tgz"):
        filename = f"{name}.tgz"
    elif os.path.exists(f"{directory}/{name}.tar.gz"):
        filename = f"{name}.tar.gz"
    else:
        failed_msg = f"{name} is not in the correct tar.gz or tgz format!"
        raise Exception(failed_msg)

    # Create the target directory if it doesn't exist
    try:
        os.makedirs(newlocation, exist_ok=True)
    except Exception as e:
        raise Exception(f"Failed to create target directory: {str(e)}")

    if striplevel:
        alternative_untar = None
        cmd = f"tar xvfz --strip {striplevel} {directory}/{filename} -C {newlocation} > /dev/null"
        exit_status = os.system(cmd)

        if int(exit_status) != 0:
            print(f"FAILED: method 1 - {cmd}")
            alternative_untar = True

        if alternative_untar:
            cmd = f"tar xvfz {directory}/{filename} --strip-components={striplevel} -C {newlocation} > /dev/null"
            exit_status = os.system(cmd)
            if int(exit_status) != 0:
                failed_message = f"FAILED: method 1 & 2 - {cmd}"
                raise Exception(failed_message)
    else:
        cmd = f"tar xvfz {directory}/{filename} -C {newlocation} > /dev/null"
        exit_status = os.system(cmd)
        if int(exit_status) != 0:
            failed_message = f"FAILED: {cmd}"
            raise Exception(failed_message)

    return newlocation

def get_file_age(file_path: str) -> Optional[int]:
    """Returns the age of a file in seconds since last modification."""
    try:
        mtime_file = int((os.stat(file_path)[-2]))
    except Exception:
        return None

    try:
        time_elapse = int(time()) - mtime_file
        return time_elapse
    except Exception:
        return None

def extract_tar_gz(file_path: str, extract_path: str = '.') -> None:
    """Extracts a tar.gz file to a specified location using the tarfile module."""
    try:
        # Ensure the extract path exists
        os.makedirs(extract_path, exist_ok=True)
        
        with tarfile.open(file_path, 'r:gz') as tar:
            # Extract all contents into the specified directory
            tar.extractall(path=extract_path)
            print(f'Extracted all files to {extract_path}')
    except tarfile.ReadError as e:
        print(f'Error: Invalid or corrupted tar file: {str(e)}')
        raise
    except PermissionError as e:
        print(f'Error: Permission denied: {str(e)}')
        raise
    except Exception as e:
        print(f'Error extracting files: {str(e)}')
        raise