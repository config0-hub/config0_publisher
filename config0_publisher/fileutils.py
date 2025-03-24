#!/usr/bin/env python

import tarfile
import os
from typing import List, Optional
import sys
import re
from time import time
from zipfile import ZipFile

def zip_file(filename: str, srcfile: str = ".env", filedirectory: Optional[str] = None) -> None:
    pwd = os.getcwd()
    filedirectory = filedirectory or pwd

    dstfile = f"{filename}.zip"
    ZipFile(dstfile, mode='w').write(srcfile)
    os.chdir(pwd)
    print(f"file zipped here {os.path.join(filedirectory, dstfile)}")

def list_all_files(rootdir: str, ignores: List[str] = [".pyc$", ".swp$"]) -> List[str]:
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
    count = 0
    with tarfile.open(file_path, 'r:gz') as tar:
        for member in tar.getmembers():
            if member.isfile():
                count += 1
    return count

def zipcli(src: str, dst: str, filename: str, exit_error: bool = True) -> Optional[str]:
    if os.path.exists(src):
        try:
            exit_status = os.system(f"cd {src} && zip -r {dst}/{filename}.zip .")
            if int(exit_status) != 0:
                raise Exception("zip-ing")
        except:
            if exit_error:
                raise Exception("zip-ing")
            return False
    else:
        print(f"Source {src} does not exists.\n")
        if exit_error:
            sys.exit(78)
        return False

    return f"{filename}.zip"

def unzipcli(directory: str, name: str, newlocation: str, exit_error: bool = True) -> Optional[str]:
    if "zip" in name:
        filename = name
    elif os.path.exists(f"{directory}/{name}.zip"):
        filename = f"{name}.zip"
    else:
        print(f"\n{name} is not in the correct .zip format!\n")
        if exit_error:
            sys.exit(78)
        return False

    cmd = f"unzip -o {directory}/{filename} -d {newlocation}/ > /dev/null"
    exit_status = os.system(cmd)

    if int(exit_status) != 0:
        failed_message = f"FAILED: {cmd}"
        print(failed_message)
        if not exit_error:
            return False
        raise Exception(failed_message)

    return newlocation

def targz(srcdir: str, dstdir: str, filename: str, verbose: bool = True) -> str:
    """This will tar a file to a new location"""
    flags = "cvf" if verbose else "cv"
    tarfile = f"{os.path.join(dstdir, filename)}.tar.gz"

    if os.path.exists(srcdir):
        cmd = f"cd {srcdir}; tar {flags} - . | gzip -n > {tarfile}"
        exit_status = os.system(cmd)
        if int(exit_status) != 0:
            raise Exception(f"{cmd} failed")
    else:
        raise Exception(f"Source {srcdir} does not exists.\n")

    count = count_files_targz(tarfile)

    if count == 0:
        raise Exception("targz with zero files!")

    return tarfile

def un_targz(directory: str, name: str, newlocation: str, striplevel: Optional[int] = None) -> str:
    """This will untar a file to a new location"""
    if "tar.gz" in name or "tgz" in name:
        filename = name
    elif os.path.exists(f"{directory}/{name}.tgz"):
        filename = f"{name}.tgz"
    elif os.path.exists(f"{directory}/{name}.tar.gz"):
        filename = f"{name}.tar.gz"
    else:
        failed_msg = f"{name} is not in the correct tar.gz or tgz format!"
        raise Exception(failed_msg)

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
    try:
        mtime_file = int((os.stat(file_path)[-2]))
    except:
        mtime_file = None

    if not mtime_file: 
        return

    try:
        time_elapse = int(time()) - mtime_file
    except:
        time_elapse = None

    return time_elapse

def extract_tar_gz(file_path: str, extract_path: str = '.') -> None:
    with tarfile.open(file_path, 'r:gz') as tar:
        # Extract all contents into the specified directory
        tar.extractall(path=extract_path)
        print(f'Extracted all files to {extract_path}')
