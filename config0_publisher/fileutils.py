#!/usr/bin/env python

import tarfile
import os
import sys
import glob
import fnmatch
import re
from time import time
from zipfile import ZipFile

def zip_file(filename,srcfile=".env",filedirectory=None):
  
    pwd = os.getcwd()

    if not filedirectory: 
        filedirectory = pwd
  
    os.chdir(filedirectory)

    dstfile = "{}.zip".format(filename)

    ZipFile(dstfile, mode='w').write(srcfile)

    os.chdir(pwd)
  
    print(("file zipped here {}".format(os.path.join(filedirectory,
                                                     dstfile))))

def list_all_files(rootdir,ignores=[ ".pyc$", ".swp$"]):

    fileList = []

    if not os.path.exists(rootdir): 
        return fileList

    for root, subFolders, files in os.walk(rootdir):

        tempList = []

        for file in files:
            f = os.path.join(root,file)
            tempList.append(f)

        for d in subFolders:
            g = os.path.join(root,d)
            tempList.append(g)

        if not tempList:
            continue

        if not ignores:
            fileList.extend(tempList)
            continue

        for file in tempList:

            add = True

            for ignore in ignores:
                if re.search(ignore,file):
                    add = False
                    break

            if add: 
                fileList.append(file)

    return fileList

def count_files_targz(file_path):

    count = 0

    with tarfile.open(file_path, 'r:gz') as tar:
        for member in tar.getmembers():
            if member.isfile():
                count += 1

    return count
def zipcli(src,dst,filename,exit_error=True):

    if os.path.exists(src):
        try:
            exit_status = os.system("cd %s && zip -r %s/%s.zip ." % (src,dst,filename))
            if int(exit_status) != 0:
                raise Exception("zip-ing")
        except Exception:
            if exit_error:
                raise Exception("zip-ing")
            return False
    else:
        print(("Source %s does not exists.\n" % src))

        if exit_error:
            sys.exit(78)

        return False

    return "{}.zip".format(os.path.join(dst,filename))

def unzipcli(directory,name,newlocation,exit_error=True):

    if "zip" in name:
        filename = name
    elif os.path.exists(directory+"/"+name+".zip"):
        filename = name+".zip"
    else:
        print(("\n%s is not in the correct .zip format!\n" % name))

        if exit_error:
            sys.exit(78)

        return False

    cmd = "unzip -o %s/%s -d %s/ > /dev/null" % (directory,filename,newlocation)
    exit_status = os.system(cmd)

    if int(exit_status) != 0:
        failed_message = "FAILED: {}".format(cmd)
        print(failed_message)
        if not exit_error:
            return False
        raise Exception(failed_message)

    return newlocation

def targz(srcdir,dstdir,filename,verbose=True):

    '''This will tar a file to a new location'''

    if verbose:
        flags = "cvf"
    else:
        flags = "cv"

    tarfile = "{}.tar.gz".format(os.path.join(dstdir,
                                              filename))

    if os.path.exists(srcdir):
        cmd = "cd %s; tar %s - . | gzip -n > %s" % (srcdir,
                                                    flags,
                                                    tarfile)
        exit_status = os.system(cmd)

        if int(exit_status) != 0:
            raise Exception("{} failed".format(cmd))
    else:
        raise Exception(("Source %s does not exists.\n" % srcdir))

    count = count_files_targz(tarfile)

    if count == 0:
        raise Exception("targz with zero files!")

    return tarfile

def un_targz(directory,name,newlocation,striplevel=None):

    '''This will untar a file to a new location'''

    if "tar.gz" in name or "tgz" in name:
        filename = name
    elif os.path.exists(directory+"/"+name+".tgz"):
        filename = name+".tgz"
    elif os.path.exists(directory+"/"+name+".tar.gz"):
        filename = name+".tar.gz"
    else:
        failed_msg = "%s is not in the correct tar.gz or tgz format!" % name
        raise Exception(failed_msg)

    cmd = None

    if striplevel:
        alternative_untar = None

        # Depending on the tar, there are different options
        cmd = "tar xvfz --strip %d %s/%s -C %s > /dev/null" % (striplevel,
                                                               directory,
                                                               filename,
                                                               newlocation)
        exit_status = os.system(cmd)

        if int(exit_status) != 0:
            print("FAILED: method 1 - {}".format(cmd))
            alternative_untar = True

        if alternative_untar:
            cmd = "tar xvfz %s/%s --strip-components=%d -C %s > /dev/null" % (directory,
                                                                              filename,
                                                                              striplevel,
                                                                              newlocation)
            exit_status = os.system(cmd)

            if int(exit_status) != 0:
                failed_message = "FAILED: method 1 & 2 - {}".format(cmd)
                raise Exception(failed_message)
    else:
        cmd = "tar xvfz %s/%s -C %s > /dev/null" % (directory,
                                                    filename,
                                                    newlocation)
        exit_status = os.system(cmd)

        if int(exit_status) != 0:
            failed_message = "FAILED: {}".format(cmd)
            raise Exception(failed_message)

    return newlocation

def get_file_age(file_path):

    try:
        mtime_file = int((os.stat(file_path)[-2]))
    except Exception:
        mtime_file = None

    if not mtime_file: 
        return

    try:
        time_elapse = int(time()) - mtime_file
    except Exception:
        time_elapse = None

    return time_elapse
def extract_tar_gz(file_path, extract_path='.'):

    with tarfile.open(file_path, 'r:gz') as tar:
        # Extract all contents into the specified directory
        tar.extractall(path=extract_path)
        print(f'Extracted all files to {extract_path}')
