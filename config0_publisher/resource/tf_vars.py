#!/usr/bin/env python

import json
from ast import literal_eval
from typing import Any, Dict, List, Optional, Tuple, Union

def tf_iter_to_str(obj: Any) -> str:
    """
    Convert iterables (lists/dicts) or other objects to properly formatted JSON strings.
    """
    if isinstance(obj, (list, dict)):
        try:
            new_obj = json.dumps(literal_eval(json.dumps(obj)))
        except (ValueError, SyntaxError, TypeError):
            new_obj = json.dumps(obj).replace("'", '"')
        return new_obj

    try:
        new_obj = json.dumps(literal_eval(obj))
    except (ValueError, SyntaxError, TypeError):
        new_obj = obj

    return new_obj


def get_tf_bool(value: Any) -> Union[str, Any]:
    """
    Convert various boolean and None-like values to Terraform-compatible strings.
    """
    bool_none = [
        "None", "none", "null", "NONE", "None", None
    ]

    bool_false = [
        "false", "False", "FALSE", False
    ]

    bool_true = [
        "TRUE", "true", "True", True
    ]

    if value in bool_none:
        return 'null'

    if value in bool_false:
        return 'false'

    if value in bool_true:
        return 'true'

    return value


def tf_map_list_fix_value(value: Any) -> Tuple[Any, Optional[bool]]:
    """
    Fix and validate list or map values for Terraform compatibility.
    Returns the fixed value and a status flag.
    """
    # Check object type and convert to string
    if isinstance(value, (dict, list)):
        value = json.dumps(value)

    # Check if string object is a list or dict
    map_list_prefixes = ["[", "{"]
    map_list_suffixes = ["]", "}"]
    status = None

    try:
        first_char = value[0]
    except (IndexError, TypeError):
        msg = f"Cannot determine first character for value {value} of type {type(value)}"
        raise ValueError(msg)

    if not first_char:
        msg = f"Empty string or None value passed: {value} of type {type(value)}"
        raise ValueError(msg)

    if first_char not in map_list_prefixes:
        return value, status

    # Map or list detected
    status = True
    value = value.replace("'", '"')

    if value[0] not in map_list_prefixes and value[0] in ["'", '"']:
        msg = f"The first character should be one of {map_list_prefixes}"
        raise ValueError(msg)

    if value[-1] not in map_list_suffixes and value[-1] in ["'", '"']:
        msg = f"The last character should be one of {map_list_suffixes}"
        raise ValueError(msg)

    return value, status


def tf_number_value(value: Any) -> Tuple[Union[int, float, Any], Optional[str]]:
    """
    Convert and identify numeric values for Terraform.
    Returns the converted value and its type ('int', 'float', or None).
    """
    try:
        value0 = value[0]
    except (IndexError, TypeError):
        value0 = None

    if value0 and value0 in ["0", 0]:
        return 0, False

    if "." in str(value):
        try:
            eval_value = float(value)
            value_type = "float"
        except (ValueError, TypeError):
            eval_value = value
            value_type = None
    else:
        try:
            eval_value = int(value)
            value_type = "int"
        except (ValueError, TypeError):
            eval_value = value
            value_type = None

    return eval_value, value_type