#!/usr/bin/env python

import os
from typing import List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class DataClassKwargs:
    """
    creates a dataclass by taking keys and values
    from the provided kwargs
    """

    kwargs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for k, v in self.kwargs.items():
            setattr(self, k, v)


@dataclass
class DataClassOsEnvVars:
    """
    creates a dataclass by taking env vars
    making them lower case as an attribute
    in a class

    this only works with strings since os env vars
    are strings
    """

    keys: List[str]

    def __post_init__(self):
        for k in self.keys:

            if k not in os.environ:
                continue

            if not os.environ.get(k):
                continue

            setattr(self, k.lower(), str(os.environ[k]))


def dict_to_classobj(values):
    return DataClassKwargs(kwargs=values)


def os_environ_to_classobj(keys):
    return DataClassOsEnvVars(keys=keys)


class SetClassVarsHelper:

    def __init__(self, set_env_vars=None, kwargs=None, env_vars=None, default_values=None, set_default_null=None):

        self.set_env_vars = set_env_vars or None
        self.kwargs = kwargs or {}
        self.env_vars = env_vars or {}
        self.default_values = default_values or {}
        self.set_default_null = set_default_null

        # track the class vars set with this
        self._vars_set = {}

    def set_class_vars_srcs(self):

        if not self.set_env_vars:
            return

        env_vars_keys = list(self.set_env_vars.keys())

        if self.default_values:
            env_vars_keys.extend(self.default_values.keys())

        for env_var_key in env_vars_keys:

            if env_var_key in self.kwargs:
                self._vars_set[env_var_key] = self.kwargs[env_var_key]
                _expression = f'self.{env_var_key} = "{self.kwargs[env_var_key]}"'
            elif env_var_key.upper() in self.env_vars:
                self._vars_set[env_var_key] = self.env_vars[env_var_key.upper()]
                _expression = f'self.{env_var_key} = "{self.env_vars[env_var_key.upper()]}"'
            elif env_var_key.upper() in os.environ:
                self._vars_set[env_var_key] = os.environ[env_var_key.upper()]
                _expression = f'self.{env_var_key} = "{os.environ[env_var_key.upper()]}"'
            elif env_var_key.lower() in self.default_values:
                self._vars_set[env_var_key.lower()] = self.default_values[env_var_key.lower()]
                _expression = f'self.{env_var_key.lower()} = "{self.default_values[env_var_key.lower()]}"'
            else:
                _expression = None

            if _expression:
                exec(_expression)
                continue

            if self.set_env_vars.get(env_var_key):  # must_exists
                raise Exception(f"variable {env_var_key} needs to be set")

            if self.set_default_null:
                self._vars_set[env_var_key] = None
                print(f'set_class_vars_srcs - default null - self.{env_var_key}=None')
                exec(f'self.{env_var_key}=None')
