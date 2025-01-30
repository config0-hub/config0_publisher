#!/usr/bin/env python

import json
from ast import literal_eval

def tf_iter_to_str(obj):

    if isinstance(obj,list) or isinstance(obj,dict):
        try:
            new_obj = json.dumps(literal_eval(json.dumps(obj)))
        except Exception:
            new_obj = json.dumps(obj).replace("'",'"')

        return new_obj

    try:
        new_obj = json.dumps(literal_eval(obj))
    except Exception:
        new_obj = obj

    return new_obj

def get_tf_bool(value):

    bool_none = [ "None",
                  "none",
                  "null",
                  "NONE",
                  "None",
                  None ]

    bool_false = [ "false",
                   "False",
                   "FALSE",
                   False ]

    bool_true = [ "TRUE",
                  "true",
                  "True",
                  True ]

    if value in bool_none:
        return 'null'

    if value in bool_false:
        return 'false'

    if value in bool_true:
        return 'true'

    return value

def tf_map_list_fix_value(_value):

    # check object type
    # convert to string
    if isinstance(_value,dict):
        _value = json.dumps(_value)

    if isinstance(_value,list):
        _value = json.dumps(_value)

    # check if string object is a list or dict
    _map_list_prefixes = ["[","{"]
    _map_list_suffixes = ["]","}"]

    _status = None

    try:
        _first_char = _value[0]
    except Exception:
        _first_char = None

    if not _first_char:
        msg = "cannot determine first character for _value {} type {}".format(_value,
                                                                              type(_value))

        raise Exception(msg)

    if _value[0] not in _map_list_prefixes:
        return _value,_status

    # map or list?
    _status = True
    _value = _value.replace("'",'"')

    if _value[0] not in _map_list_prefixes and _value[0] in ["'",'"']:
        msg = "the first character should be {}".format(_map_list_prefixes)
        raise Exception(msg)

    if _value[-1] not in _map_list_suffixes and _value[-1] in ["'",'"']:
        msg = "the last character should be {}".format(_map_list_suffixes)
        raise Exception(msg)

    return _value,_status

def tf_number_value(value):

    try:
        value0 = value[0]
    except Exception:
        value0 = None

    if value0 and value0 in [ "0", 0 ]:
        return 0,False

    if "." in str(value):

        try:
            eval_value = float(value)
            value_type = "float"
        except Exception:
            eval_value = value
            value_type = None
    else:

        try:
            eval_value = int(value)
            value_type = "int"
        except Exception:
            eval_value = value
            value_type = None

    return eval_value,value_type