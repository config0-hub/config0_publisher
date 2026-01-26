#!/usr/bin/env python

import string
import random
import datetime
import json
import os
import hashlib
from string import ascii_lowercase
from pathlib import Path

from config0_publisher.loggerly import Config0Logger
from config0_publisher.shellouts import mkdir
from config0_publisher.shellouts import rm_rf

class DateTimeJsonEncoder(json.JSONEncoder):

    def default(self, obj):

        if isinstance(obj, datetime.datetime):
            newobject = '-'.join([str(element) for element in list(obj.timetuple())][0:6])
            return newobject

        return json.JSONEncoder.default(self, obj)

def print_json(results):
    print(json.dumps(results, sort_keys=True, cls=DateTimeJsonEncoder, indent=4))

def nice_json(results):
    return json.dumps(results, sort_keys=True, cls=DateTimeJsonEncoder, indent=4)

# ref 34532045732
def to_jsonfile(values, filename, exec_dir=None):
    """
    Write values to a JSON file in the config0_resources directory.

    Args:
        values (dict): Data to write to JSON file
        filename (str): Name of the file to create
        exec_dir (str, optional): Execution directory. Defaults to current directory.

    Returns:
        bool: True if write successful, False otherwise

    Example:
        >>> to_jsonfile({"key": "value"}, "resource.json")
        Successfully wrote contents to /path/to/config0_resources/resource.json
        True
    """

    if not exec_dir: 
        exec_dir = os.getcwd()

    file_dir = os.path.join(exec_dir, "config0_resources")
    file_path = os.path.join(file_dir, filename)

    # Create directory if it doesn't exist
    Path(file_dir).mkdir(parents=True, exist_ok=True)

    try:
        with open(file_path, "w") as file:
            file.write(json.dumps(values))
        status = True
        print("-"*32)
        print(f"   ----- Successfully wrote contents to {file_path}")
        print("-"*32)
    except:
        print("-"*32)
        print(f"   ----- Failed to write contents to {file_path}")
        print("-"*32)
        status = False

    return status

def convert_str2list(_object, split_char=None):

    if split_char:
        entries = [entry.strip() for entry in _object.split(split_char)]
    else:
        entries = [entry.strip() for entry in _object.split(" ")]

    return entries

def convert_str2json(_object, exit_error=None):

    if isinstance(_object, dict):
        return _object

    if isinstance(_object, list):
        return _object

    try:
        _object = json.loads(_object)
        status = True
    except:
        status = False

    if not status:
        try:
            _object = eval(_object)
        except:
            if exit_error:
                exit(13)

            return False

    return _object

def to_list(_object, split_char=None, exit_error=None):

    return convert_str2list(_object,
                            split_char=split_char,
                            exit_error=exit_error)

def to_json(_object, exit_error=None):

    return convert_str2json(_object,
                            exit_error=exit_error)

def get_hash(data):
    """
    Determines a consistent hash of a data object across platforms and environments
    
    Args:
        data: The data to hash (can be str, bytes, or other Python objects)
        
    Returns:
        String hash or False on error
    """
    import hashlib
    import json
    import logging
    
    # Setup logger (assuming Config0Logger is a custom logger class)
    logger = logging.getLogger("get_hash")  # Replace with your logger if needed
    
    # Convert data to bytes with consistent serialization
    try:
        if isinstance(data, bytes):
            # Already in bytes format
            data_bytes = data
        elif isinstance(data, str):
            # Convert string to UTF-8 bytes
            data_bytes = data.encode('utf-8')
        elif isinstance(data, (dict, list, tuple, set)):
            # Handle collections with consistent ordering
            if isinstance(data, dict):
                # Sort dictionary keys for consistent serialization
                data_bytes = json.dumps(data, sort_keys=True).encode('utf-8')
            elif isinstance(data, set):
                # Sort set elements for consistent serialization
                data_bytes = json.dumps(sorted(list(data))).encode('utf-8')
            else:
                # Lists and tuples maintain their order in JSON
                data_bytes = json.dumps(data).encode('utf-8')
        elif isinstance(data, (int, float, bool, type(None))):
            # Handle primitive types
            data_bytes = str(data).encode('utf-8')
        else:
            # For other object types, convert to string representation
            # Note: This may not be consistent for all object types
            logger.warning(f"Hashing non-primitive type {type(data)}. Results may be inconsistent.")
            data_bytes = str(data).encode('utf-8')
    except Exception as e:
        logger.error(f"Failed to prepare data for hashing: {str(e)}")
        return False
    
    # Calculate hash using hashlib only (no shell fallback)
    try:
        calculated_hash = hashlib.md5(data_bytes).hexdigest()
        return calculated_hash
    except Exception as e:
        logger.error(f"Could not calculate hash: {str(e)}")
        return False

def id_generator2(size=6, lowercase=True):

    if lowercase:
        return id_generator(size=size, chars=ascii_lowercase)

    return id_generator(size=size)

# dup 4523452346
def id_generator(size=6, chars=string.ascii_uppercase + string.digits):

    """generates id randomly"""

    return ''.join(random.choice(chars) for x in range(size))

def get_dict_frm_file(file_path):

    """
    looks at the file_path in the format
    key=value

    and parses it and returns a dictionary
    """

    sparams = {}

    rfile = open(file_path, "r")

    non_blank_lines = (line.strip() for line in rfile.readlines() if line.strip())

    for bline in non_blank_lines:
        key, value = bline.split("=")
        sparams[key] = value

    return sparams

class OnDiskTmpDir(object):

    def __init__(self, **kwargs):

        self.tmpdir = kwargs.get("tmpdir")

        if not self.tmpdir:
            self.tmpdir = "/tmp"

        self.subdir = kwargs.get("subdir", "ondisktmp")

        if self.subdir:
            self.basedir = f"{self.tmpdir}/{self.subdir}"
        else:
            self.basedir = self.tmpdir

        self.classname = "OnDiskTmpDir"

        mkdir("/tmp/ondisktmpdir/log")

        self.logger = Config0Logger(self.classname)

        if kwargs.get("init", True):
            self.set_dir(**kwargs)

    def set_dir(self, **kwargs):

        createdir = kwargs.get("createdir", True)

        self.fqn_dir, self.dir = generate_random_path(self.basedir,
                                                     folder_depth=1,
                                                     folder_length=16,
                                                     createdir=createdir,
                                                     string_only=True)

        return self.fqn_dir

    # TODO remove kwargs
    def get(self, **kwargs):

        if not self.fqn_dir:
            msg = "fqn_dir has not be set"
            raise Exception(msg)

        self.logger.debug(f'Returning fqn_dir "{self.fqn_dir}"')

        return self.fqn_dir

    # TODO remove kwargs
    def delete(self, **kwargs):

        self.logger.debug(f'Deleting fqn_dir "{self.fqn_dir}"')

        return rm_rf(self.fqn_dir)

def generate_random_path(basedir, folder_depth=1, folder_length=16, createdir=False, string_only=None):

    """
    returns random folder path with specified parameters
    """

    cwd = basedir

    for _ in range(folder_depth):

        if string_only:
            random_dir = id_generator(folder_length,
                                      chars=string.ascii_lowercase)
        else:
            random_dir = id_generator(folder_length)

        cwd = cwd + "/" + random_dir

    if createdir:
        mkdir(cwd)

    return cwd, random_dir

# dup 34523532452t33t
def get_values_frm_json(json_file=None):
    if not json_file:
        return

    if not os.path.exists(json_file):
        print(f"g0e: WARN: json {json_file} does not exists")
        return

    try:
        with open(json_file) as json_file:
            values = json.load(json_file)
        print(f"g0e - Successfully retrieved values from {json_file}")
    except:
        values = None
        print(f"g0e - ERROR: could not retrieved from json file {json_file}")

    return values

def eval_str_to_join(str_obj):
    for j in "\n".join(str_obj):
        if len(j) in [0, 1]:
            continue
        return True
    return

