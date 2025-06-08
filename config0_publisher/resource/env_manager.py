import os
from config0_publisher.variables import EnvVarsToClassVars

class EnvManager:
    """
    Handles environment variable management and class variable synchronization.
    """
    
    def __init__(self, os_env_prefix=None, app_name=None, app_dir=None):
        self.os_env_prefix = os_env_prefix
        self.app_name = app_name
        self.app_dir = app_dir
        
    def set_env_vars(self, env_vars=None, clobber=False):
        auto_clobber_keys = [
            "CHROOTFILES_DEST_DIR",
            "WORKING_DIR"
        ]

        if not env_vars:
            return

        for _k, _v in env_vars.items():
            if self.os_env_prefix and self.os_env_prefix in _k:
                _key = _k
            else:
                _key = _k.upper()

            if _v is None:
                if os.environ.get("JIFFY_ENHANCED_LOG"):
                    print(f"{_key} -> None - skipping")
                continue

            if _key in os.environ and _key in auto_clobber_keys:
                if os.environ.get("JIFFY_ENHANCED_LOG"):
                    print(f"{_key} -> {_v} already set/will clobber")
            elif _key in os.environ and not clobber:
                if os.environ.get("JIFFY_ENHANCED_LOG"):
                    print(f"{_key} -> {_v} already set as {os.environ[_key]}")
                continue

            if os.environ.get("JIFFY_ENHANCED_LOG"):
                print(f"{_key} -> {_v}")

            os.environ[_key] = str(_v)
            
    def set_os_env_prefix(self):
        if self.os_env_prefix: 
            return

        if self.app_name == "terraform":
            self.os_env_prefix = "TF_VAR"
        elif self.app_name == "ansible":
            self.os_env_prefix = "ANS_VAR"
            
    def get_os_env_prefix_envs(self, remove_os_environ=True):
        """
        Get OS env prefix vars e.g. TF_VAR_ipadddress and return
        the variables as lowercase without the prefix, e.g. ipaddress
        """
        if not self.os_env_prefix:
            return {}

        _split_key = f"{self.os_env_prefix}_"
        inputargs = {}

        for i in os.environ.keys():
            if self.os_env_prefix not in i: 
                continue

            _var = i.split(_split_key)[1].lower()
            inputargs[_var] = os.environ[i]

            if remove_os_environ:
                del os.environ[i]

        return inputargs
        
    def get_app_env_keys(self):
        if not self.os_env_prefix:
            return {}

        try:
            return [_key for _key in os.environ.keys() if self.os_env_prefix in _key]
        except:
            return None
            
    def get_env_var(self, variable, default=None, must_exists=None):
        _value = os.environ.get(variable)

        if _value:
            return _value

        if self.os_env_prefix:
            _value = os.environ.get(f"{self.os_env_prefix}_{variable}")

            if _value:
                return _value

            _value = os.environ.get(f"{self.os_env_prefix}_{variable.lower()}")

            if _value:
                return _value

            _value = os.environ.get(f"{self.os_env_prefix}_{variable.upper()}")

            if _value:
                return _value

        if default:
            return default

        if not must_exists:
            return

        raise Exception(f"{variable} does not exist")
        
    def insert_os_env_prefix_envs(self, env_vars, exclude_vars=None):
        _env_keys = self.get_app_env_keys()

        if not _env_keys: 
            return

        if not exclude_vars:
            exclude_vars = []

        _split_key = f"{self.os_env_prefix}_"

        for _env_key in _env_keys:
            _var = _env_key.split(_split_key)[1].lower()

            if _var in exclude_vars: 
                continue

            _env_value = os.environ.get(_env_key)

            if not _env_key: 
                continue

            if _env_value in ["False", "false", "null", False]: 
                _env_value = "false"

            if _env_value in ["True", "true", True]: 
                _env_value = "true"

            env_vars[_env_key] = _env_value