#!/usr/bin/env python

import os
from typing import List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class DataClassKwargs:
    """Creates a dataclass by taking keys and values from provided kwargs."""

    kwargs: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        for k, v in self.kwargs.items():
            setattr(self, k, v)


@dataclass
class DataClassOsEnvVars:
    """
    Creates a dataclass by taking env vars and making them lowercase attributes.
    Only works with strings since OS env vars are strings.
    """

    keys: List[str]

    def __post_init__(self):
        for k in self.keys:
            try:
                env_value = os.environ.get(k)
                if env_value:
                    setattr(self, k.lower(), str(env_value))
            except Exception:
                continue


def dict_to_classobj(values):
    """Converts a dictionary to a DataClassKwargs object."""
    return DataClassKwargs(kwargs=values)


def os_environ_to_classobj(keys):
    """Converts specified OS environment variables to a DataClassOsEnvVars object."""
    return DataClassOsEnvVars(keys=keys)


class SetClassVarsHelper:
    """Helper class to set class variables from different sources with priority."""

    def __init__(self, set_env_vars=None, kwargs=None, env_vars=None, default_values=None, set_default_null=None):
        """Initialize the helper with configuration sources."""
        self.set_env_vars = set_env_vars or None
        self.kwargs = kwargs or {}
        self.env_vars = env_vars or {}
        self.default_values = default_values or {}
        self.set_default_null = set_default_null

        # track the class vars set with this
        self._vars_set = {}

    def set_class_vars_srcs(self):
        """Set class variables from different sources based on priority."""
        if not self.set_env_vars:
            return

        env_vars_keys = list(self.set_env_vars.keys())

        if self.default_values:
            env_vars_keys.extend(self.default_values.keys())

        for env_var_key in env_vars_keys:
            try:
                if env_var_key in self.kwargs:
                    self._vars_set[env_var_key] = self.kwargs[env_var_key]
                    setattr(self, env_var_key, self.kwargs[env_var_key])
                elif env_var_key.upper() in self.env_vars:
                    self._vars_set[env_var_key] = self.env_vars[env_var_key.upper()]
                    setattr(self, env_var_key, self.env_vars[env_var_key.upper()])
                elif env_var_key.upper() in os.environ:
                    self._vars_set[env_var_key] = os.environ[env_var_key.upper()]
                    setattr(self, env_var_key, os.environ[env_var_key.upper()])
                elif env_var_key.lower() in self.default_values:
                    self._vars_set[env_var_key.lower()] = self.default_values[env_var_key.lower()]
                    setattr(self, env_var_key.lower(), self.default_values[env_var_key.lower()])
                elif self.set_env_vars.get(env_var_key):  # must_exists
                    raise Exception(f"Variable {env_var_key} needs to be set")
                elif self.set_default_null:
                    self._vars_set[env_var_key] = None
                    print(f'set_class_vars_srcs - default null - self.{env_var_key}=None')
                    setattr(self, env_var_key, None)
            except Exception as e:
                if self.set_env_vars.get(env_var_key):  # If it's required, re-raise
                    raise Exception(f"Error setting variable {env_var_key}: {str(e)}")
                # Otherwise continue to next variable