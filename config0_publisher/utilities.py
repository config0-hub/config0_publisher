#!/usr/bin/env python

import string
import random
import datetime
import json
import os
import hashlib
from string import ascii_lowercase

from config0_publisher.loggerly import Config0Logger
from config0_publisher.shellouts import mkdir
from config0_publisher.shellouts import rm_rf


class DateTimeJsonEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime objects by converting them to strings."""
    
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            newobject = '-'.join([str(element) for element in list(obj.timetuple())][0:6])
            return newobject
        return json.JSONEncoder.default(self, obj)


def print_json(results):
    """Print JSON results in a pretty format."""
    print(json.dumps(results, sort_keys=True, cls=DateTimeJsonEncoder, indent=4))


def nice_json(results):
    """Return a pretty-formatted JSON string."""
    return json.dumps(results, sort_keys=True, cls=DateTimeJsonEncoder, indent=4)


def convert_str2list(_object, split_char=None):
    """Convert a string to a list by splitting on the specified character."""
    if split_char:
        entries = [entry.strip() for entry in _object.split(split_char)]
    else:
        entries = [entry.strip() for entry in _object.split(" ")]
    return entries


def convert_str2json(_object, exit_error=None):
    """Convert a string to a JSON object."""
    if isinstance(_object, (dict, list)):
        return _object

    try:
        return json.loads(_object)
    except Exception:
        try:
            return eval(_object)
        except Exception:
            if exit_error:
                exit(13)
            return False


def to_list(_object, split_char=None, exit_error=None):
    """Convert an object to a list."""
    return convert_str2list(_object, split_char=split_char)


def to_json(_object, exit_error=None):
    """Convert an object to JSON."""
    return convert_str2json(_object, exit_error=exit_error)


def get_hash(data):
    """
    Determine a consistent hash of a data object across platforms and environments.
    
    Args:
        data: The data to hash (can be str, bytes, or other Python objects)
        
    Returns:
        String hash or False on error
    """
    try:
        # Convert data to bytes with consistent serialization
        if isinstance(data, bytes):
            data_bytes = data
        elif isinstance(data, str):
            data_bytes = data.encode('utf-8')
        elif isinstance(data, (dict, list, tuple, set)):
            if isinstance(data, dict):
                data_bytes = json.dumps(data, sort_keys=True).encode('utf-8')
            elif isinstance(data, set):
                data_bytes = json.dumps(sorted(list(data))).encode('utf-8')
            else:
                data_bytes = json.dumps(data).encode('utf-8')
        elif isinstance(data, (int, float, bool, type(None))):
            data_bytes = str(data).encode('utf-8')
        else:
            data_bytes = str(data).encode('utf-8')
    except Exception as e:
        return False
    
    # Calculate hash
    try:
        calculated_hash = hashlib.md5(data_bytes).hexdigest()
        return calculated_hash
    except Exception:
        return False


def id_generator2(size=6, lowercase=True):
    """Generate an ID with option for lowercase."""
    if lowercase:
        return id_generator(size=size, chars=ascii_lowercase)
    return id_generator(size=size)


def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    """Generate a random ID."""
    return ''.join(random.choice(chars) for _ in range(size))


def get_dict_frm_file(file_path):
    """
    Parse a file with key=value format and return a dictionary.
    """
    sparams = {}
    try:
        with open(file_path, "r") as rfile:
            non_blank_lines = (line.strip() for line in rfile.readlines() if line.strip())
            for bline in non_blank_lines:
                try:
                    key, value = bline.split("=", 1)  # Split on first occurrence only
                    sparams[key] = value
                except ValueError:
                    pass  # Skip lines that don't have the expected format
    except (IOError, OSError) as e:
        # Handle file reading errors
        pass
    
    return sparams


class OnDiskTmpDir(object):
    """Manage temporary directories on disk."""

    def __init__(self, **kwargs):
        """Initialize the temporary directory manager."""
        self.tmpdir = kwargs.get("tmpdir", "/tmp")
        self.subdir = kwargs.get("subdir", "ondisktmp")
        
        if self.subdir:
            self.basedir = f"{self.tmpdir}/{self.subdir}"
        else:
            self.basedir = self.tmpdir
        
        self.classname = "OnDiskTmpDir"
        self.fqn_dir = None
        self.dir = None
        
        try:
            mkdir("/tmp/ondisktmpdir/log")
        except Exception:
            pass  # Don't fail if directory creation fails
            
        self.logger = Config0Logger(self.classname)
        
        if kwargs.get("init", True):
            self.set_dir(**kwargs)

    def set_dir(self, **kwargs):
        """Set up and create the temporary directory."""
        createdir = kwargs.get("createdir", True)
        
        try:
            self.fqn_dir, self.dir = generate_random_path(
                self.basedir,
                folder_depth=1,
                folder_length=16,
                createdir=createdir,
                string_only=True
            )
        except Exception as e:
            self.logger.error(f"Failed to create directory: {str(e)}")
            
        return self.fqn_dir

    def get(self):
        """Get the fully qualified directory path."""
        if not self.fqn_dir:
            msg = "fqn_dir has not been set"
            raise Exception(msg)
            
        self.logger.debug(f'Returning fqn_dir "{self.fqn_dir}"')
        return self.fqn_dir

    def delete(self):
        """Delete the temporary directory."""
        if not self.fqn_dir:
            self.logger.warning("No directory to delete")
            return False
            
        self.logger.debug(f'Deleting fqn_dir "{self.fqn_dir}"')
        try:
            return rm_rf(self.fqn_dir)
        except Exception as e:
            self.logger.error(f"Failed to delete directory: {str(e)}")
            return False


def generate_random_path(basedir, folder_depth=1, folder_length=16, createdir=False, string_only=None):
    """
    Generate a random folder path with specified parameters.
    """
    cwd = basedir
    random_dir = None
    
    try:
        for _ in range(folder_depth):
            if string_only:
                random_dir = id_generator(folder_length, chars=string.ascii_lowercase)
            else:
                random_dir = id_generator(folder_length)
                
            cwd = f"{cwd}/{random_dir}"
            
        if createdir:
            mkdir(cwd)
    except Exception:
        # Log error or handle gracefully
        pass
        
    return cwd, random_dir


def get_values_frm_json(json_file=None):
    """Get values from a JSON file."""
    if not json_file:
        return None
        
    if not os.path.exists(json_file):
        print(f"WARN: json {json_file} does not exist")
        return None
        
    try:
        with open(json_file, 'r') as file:
            values = json.load(file)
        print(f"Successfully retrieved values from {json_file}")
        return values
    except Exception:
        print(f"ERROR: could not retrieve from json file {json_file}")
        return None


def eval_str_to_join(str_obj):
    """Evaluate if string object needs to be joined."""
    try:
        for j in "\n".join(str_obj):
            if len(j) in [0, 1]:
                continue
            return True
    except Exception:
        pass
    return False