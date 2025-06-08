import os
import jinja2
from config0_publisher.templating import list_template_files

class TemplateManager:
    """
    Handles template rendering and file generation.
    """
    
    def __init__(self, logger, os_env_prefix=None, app_name=None, exec_dir=None, template_dir=None):
        self.logger = logger
        self.os_env_prefix = os_env_prefix
        self.app_name = app_name
        self.exec_dir = exec_dir
        self.template_dir = template_dir
        
    def _mkdir(self, dir_path):
        if os.path.exists(dir_path): 
            return

        os.makedirs(dir_path, exist_ok=True)
        
    def get_template_vars(self, **kwargs):
        # if the app_template_vars is provided, we use it, otherwise, we
        # assume it is the <APP_NAME>_EXEC_TEMPLATE_VARS
        _template_vars = kwargs.get("app_template_vars")

        if not _template_vars and self.app_name:
            _template_vars = f"{self.app_name}_EXEC_TEMPLATE_VARS"

        if not os.environ.get(_template_vars.upper()): 
            _template_vars = "ED_EXEC_TEMPLATE_VARS"

        if os.environ.get(_template_vars.upper()):
            return [_var.strip() for _var in os.environ.get(_template_vars.upper()).split(",")]

        if not self.os_env_prefix: 
            return

        # get template_vars e.g. "ANS_VAR_<var>"
        _template_vars = []

        for _var in os.environ.keys():
            if self.os_env_prefix not in _var: 
                continue

            self.logger.debug(f"{self.os_env_prefix} found in {_var}")
            self.logger.debug(f"templating variable {_var}")
            _template_vars.append(_var)

        if not _template_vars: 
            self.logger.warn("ED_EXEC_TEMPLATE_VARS and <APP> template vars not set/given")

        return _template_vars
    
    def templify(self, **kwargs):
        clobber = kwargs.get("clobber")
        _template_vars = self.get_template_vars(**kwargs)

        if not _template_vars:
            self.logger.debug_highlight("template vars is not set or empty")
            return

        self.logger.debug_highlight(f"template vars {_template_vars} not set or empty")

        if not self.template_dir:
            self.logger.warn("template_dir not set (None) - skipping templating")
            return

        template_files = list_template_files(self.template_dir)

        if not template_files:
            self.logger.warn(f"template_files in directory {self.template_dir} empty - skipping templating")
            return

        for _file_stats in template_files:
            template_filepath = _file_stats["file"]

            file_dir = os.path.join(self.exec_dir,
                                    _file_stats["directory"])

            file_path = os.path.join(self.exec_dir,
                                     _file_stats["directory"],
                                     _file_stats["filename"].split(".ja2")[0])

            self._mkdir(file_dir)

            if os.path.exists(file_path) and not clobber:
                self.logger.warn(f"destination templated file already exists at {file_path} - skipping templifying of it")
                continue

            self.logger.debug(f"creating templated file file {file_path} from {template_filepath}")

            template_vars = {}

            if self.os_env_prefix:
                self.logger.debug(f"using os_env_prefix {self.os_env_prefix}")
                _split_char = f"{self.os_env_prefix}_"
            else:
                _split_char = None

            if not _template_vars:
                self.logger.error("_template_vars is empty")
                exit(9)

            self.logger.debug(f"_template_vars {_template_vars}")

            for _var in _template_vars:
                _value = None
                _mapped_key = None

                if self.os_env_prefix:
                    if self.os_env_prefix in _var:
                        _key = _var.split(_split_char)[1]
                        _value = os.environ.get(_var)
                    else:
                        _key = str(f"{self.os_env_prefix}_{_var}")
                        _value = os.environ.get(_key)

                    if _value: _mapped_key = _key

                if not _value:
                    _value = os.environ.get(str(_var))
                    if _value: _mapped_key = _var

                if not _value:
                    _value = os.environ.get(str(_var.upper()))
                    if _value: _mapped_key = _var.upper()

                self.logger.debug("")
                self.logger.debug(f"mapped_key {_mapped_key}")
                self.logger.debug(f"var {_var}")
                self.logger.debug(f"value {_value}")
                self.logger.debug("")

                if not _value or not _mapped_key: 
                    self.logger.warn(f"skipping templify var {_var}")
                    continue

                value = _value.replace("'", '"')

                # include both uppercase and regular keys
                template_vars[_mapped_key] = value
                template_vars[_mapped_key.upper()] = value

            self.logger.debug("")
            self.logger.debug(f"template_vars {template_vars}")
            self.logger.debug("")

            template_loader = jinja2.FileSystemLoader(searchpath="/")
            template_env = jinja2.Environment(loader=template_loader)
            template = template_env.get_template(template_filepath)
            output_text = template.render(template_vars)
            writefile = open(file_path, "w")
            writefile.write(output_text)
            writefile.close()

        return True