#!/usr/bin/env python

import concurrent.futures, json, string, os, random, subprocess
from config0_publisher.loggerly import Config0Logger as set_log

def ensure_str(obj, strip=True):

    if not isinstance(obj, str):
        try:
            new_obj = obj.decode("utf-8") if isinstance(obj, bytes) else obj
        except:
            new_obj = obj
    else:
        new_obj = obj

    if strip and isinstance(new_obj, str):
        return new_obj.strip()

    return new_obj

def mkdir(directory):
    """
    Create a directory and any necessary parent directories.
    
    Args:
        directory (str): Path to the directory to create.
        
    Returns:
        bool: True if the directory exists or was created successfully, False otherwise.
    """
    try:
        if not os.path.exists(directory):
            # Use os.makedirs instead of os.system for better portability and security
            os.makedirs(directory, exist_ok=True)
        return True
    except Exception as e:
        # Log the specific error for debugging
        print(f"Error creating directory {directory}: {e}")
        return False

def rm_rf(location):

    """uses the shell to forcefully and recursively remove a file/entire directory."""

    if not location:
        return

    if not os.path.exists(location):
        return

    try:
        os.remove(location)
        status = True
    except:
        status = False

    if status:
        return True

    if os.path.exists(location):
        try:
            os.system(f"rm -rf {location} > /dev/null 2>&1")
            status = True
        except:
            print(f"problems with removing {location}")
            status = False

        return status

def execute3(cmd, **kwargs):
    shellout_exe = ShellOutExecute(cmd, 
                                  unbuffered=None, 
                                  **kwargs)

    print(f"Executing command: {cmd}")
    shellout_exe.execute3()

    if kwargs.get("print_out", True):
        shellout_exe.print_out()

    if kwargs.get("exit_error", True) and int(shellout_exe.results["exitcode"]) != 0:
        exit(shellout_exe.results["exitcode"])

    print(f"Command executed with exit code: {shellout_exe.results['exitcode']}")
    return shellout_exe.results

def execute2(cmd, **kwargs):
    return execute3(cmd, **kwargs)

def execute3a(cmd, **kwargs):

    shellout_exe = ShellOutExecute(cmd,
                                   unbuffered=None,
                                   **kwargs)

    shellout_exe.execute3a()

    if kwargs.get("print_out"):
        shellout_exe.print_out()

    if kwargs.get("exit_error"):
        exit(shellout_exe.results["exitcode"])

    return shellout_exe.results

def execute4(cmd, **kwargs):

    return execute3a(cmd, **kwargs)

def execute5(cmd, **kwargs):

    shellout_exe = ShellOutExecute(cmd,
                                   unbuffered=None,
                                   **kwargs)

    shellout_exe.execute5()

    if kwargs.get("exit_error"):
        exit(shellout_exe.results["exitcode"])

    return shellout_exe.results

def execute7(cmd, **kwargs):

    shellout_exe = ShellOutExecute(cmd,
                                   unbuffered=None,
                                   **kwargs)

    shellout_exe.execute7()

    if kwargs.get("print_out", True):
        shellout_exe.print_out()

    if kwargs.get("exit_error"):
        exit(shellout_exe.results["exitcode"])

    return shellout_exe.results

def execute(cmd, unbuffered=False, logfile=None, print_out=True):

    """executes a shell command, returning status of execution,
    standard out, and standard error"""

    inputargs = {"unbuffered": unbuffered}

    if logfile:
        inputargs["logfile"] = logfile
        inputargs["write_logfile"] = True

    shellout_exe = ShellOutExecute(cmd,
                                   **inputargs)

    shellout_exe.popen2()

    if print_out and unbuffered:
        shellout_exe.print_out()

    return shellout_exe.results["exitcode"], shellout_exe.results["stdout"], shellout_exe.results["stderr"]

class ShellOutExecute(object):

    def __init__(self, cmd, unbuffered=None, **kwargs):

        self.logger = set_log("ShellOutExecute")

        self._set_cwd()
        self.tmpdir = kwargs.get("tmpdir", "/tmp")

        self.unbuffered = unbuffered
        self.cmd = cmd

        self.output_to_json = kwargs.get("output_to_json", True)
        self.output_queue = kwargs.get("output_queue")

        self.env_vars = kwargs.get("env_vars")
        self.unset_envs = kwargs.get("unset_envs")

        self.logfile = kwargs.get("logfile")
        self.env_vars_set = {}

        self.exit_file = kwargs.get("exit_file")

        if not self.exit_file:
            self.exit_file = os.path.join(self.tmpdir,
                                          self._id_generator(10, chars=string.ascii_lowercase))

        if not self.logfile:
            self.logfile = os.path.join(self.tmpdir,
                                        self._id_generator(10, chars=string.ascii_lowercase))

        self.logfile_handle = None

        if kwargs.get("write_logfile"):
            self.logfile_handle = open(self.logfile, "w")

        self.results = {"status": None,
                        "failed_message": None,
                        "output": None,
                        "exitcode": None}

    @staticmethod
    def _id_generator(size=6, chars=string.ascii_uppercase + string.digits):
        return ''.join(random.choice(chars) for _ in range(size))

    def _set_cwd(self):

        try:
            self.cwd = os.getcwd()
        except:
            self.logger.warn("Cannot determine current directory - setting cwd to /tmp")
            self.cwd = "/tmp"
            os.chdir(self.cwd)

        return self.cwd

    def _get_system_cmd(self):

        cmd = f'({self.cmd} 2>&1 ; echo $? > {self.exit_file}) | tee -a {self.logfile}; exit `cat {self.exit_file}`'

        return cmd

    def _cleanup_system_exe(self):

        os.remove(self.exit_file)
        os.remove(self.logfile)

    def add_unset_envs_to_cmd(self):

        if not self.unset_envs:
            return

        unset_envs = [_element.strip() for _element in self.unset_envs.split(",")]

        for _env in unset_envs:
            self.cmd = f"unset {_env}; {self.cmd}"

    def set_env_vars(self):

        if not self.env_vars:
            return

        _env_vars = self.env_vars.get()

        for ek, ev in _env_vars.items():
            if ev is None:
                ev = "None"
            elif isinstance(ev, bytes):
                ev = ev.decode("utf-8")
            elif not isinstance(ev, str):
                ev = str(ev)

            if os.environ.get("JIFFY_ENHANCED_LOG") or os.environ.get("DEBUG_STATEFUL"):
                self.logger.debug(f"key -> {ek} value -> {ev} type -> {type(ev)}")
            else:
                self.logger.debug(f"Setting environment variable {ek}, type {type(ev)}")

            self.env_vars_set[ek] = ev
            os.environ[ek] = ev

        if os.environ.get("JIFFY_ENHANCED_LOG"):

            self.logger.debug("#" * 32)
            self.logger.debug("# env vars set are")

            print((json.dumps(self.env_vars_set,
                              sort_keys=True,
                              indent=4)))

            self.logger.debug("#" * 32)

        return _env_vars

    def print_out(self):

        if not self.results:
            return

        output = self.results.get("output")

        if not output:
            return

        try:
            self.logger.debug(output)
        except:
            print(output)

    def _convert_output_to_json(self):

        if not self.output_to_json:
            return

        if isinstance(self.results["output"], dict):
            return

        try:
            output = json.loads(self.results["output"])
        except:
            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug("Could not convert output to json")
            return

        self.results["output"] = output

        return True

    def _eval_execute(self):

        if self.results["exitcode"] != 0:
            self.results["status"] = False
            self.results["failed_message"] = self.results["output"]

        else:
            self.results["status"] = True
            self._convert_output_to_json()

        if self.output_queue:
            try:
                self.output_queue.put(self.results)
            except:
                self.logger.error("Could not append the results to the output_queue")

    def set_popen_kwargs(self):

        self.popen_kwargs = {"shell": True,
                             "universal_newlines": True,
                             "stdout": subprocess.PIPE,
                             "stderr": subprocess.STDOUT}

    def run(self):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: run")

        self.set_env_vars()
        self.set_popen_kwargs()

        process = subprocess.run(self.cmd,
                                 **self.popen_kwargs)

        self.results["output"] = process.stdout

        self._add_log_file(self.results["output"])

        self.results["exitcode"] = self._eval_exitcode(process.returncode)

        self._eval_execute()

        return self.results

    def _init_popen(self):

        return subprocess.Popen(self.cmd,
                                **self.popen_kwargs)

    def _add_log_file(self, line):

        if not self.logfile_handle:
            return

        self.logfile_handle.write(line)
        self.logfile_handle.write("\n")

    def _eval_log_line(self, readline, lines):

        line = ensure_str(readline, strip=True)

        if not line:
            return

        lines.append(line)

        if self.unbuffered:
            print(line)

        self._add_log_file(line)

        return True

    def _eval_popen_exe(self, process):

        lines = []

        while True:

            readline = process.stdout.readline()
            self._eval_log_line(readline, lines)

            exitcode = process.poll()

            if exitcode is None:
                continue

            _last_lines = process.stdout.readlines()

            if _last_lines:
                for _last_line in _last_lines:
                    self._eval_log_line(_last_line, lines)
            break

        if self.logfile_handle:
            self.logfile_handle.close()

        if lines:
            self.results["output"] = "\n".join(lines)

        self.results["exitcode"] = self._eval_exitcode(exitcode)

        if exitcode != 0:
            self.results["status"] = False
        else:
            self.results["status"] = True

        self._eval_execute()

    def _popen_communicate(self, process):

        out, err = process.communicate()

        self.results["stdout"] = out
        self.results["stderr"] = err
        self.results["exitcode"] = self._eval_exitcode(process.returncode)

        return self.results

    def popen(self):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: popen")

        self.set_popen_kwargs()
        self.popen_kwargs["bufsize"] = 0

        process = self._init_popen()

        self._eval_popen_exe(process)

        return self.results

    def popen2(self):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: popen2")

        process = subprocess.Popen(self.cmd,
                                   shell=True,
                                   universal_newlines=True,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

        self._popen_communicate(process)

        return self.results

    def execute6(self):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute6")

        self.logger.debug(f"from directory {os.getcwd()} - command {self.cmd}")

        self.set_env_vars()
        self.add_unset_envs_to_cmd()

        return self.popen()

    def execute3(self):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute3")

        self.logger.debug(f"from directory {os.getcwd()} - command {self.cmd}")

        self.set_env_vars()
        self.popen()

        return self.results

    def system(self, direct_return=True):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: system")

        cmd = self._get_system_cmd()
        _return_code = os.system(cmd)

        if direct_return:
            return self._eval_exitcode(_return_code)

        # calculate the return value code
        return int(bin(_return_code).replace("0b", "").rjust(16, '0')[:8], 2)

    @staticmethod
    def _eval_exitcode(exitcode):

        try:
            return int(exitcode)
        except:
            return exitcode

    def execute3a(self):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute3a")

        self.results["exitcode"] = self.system(direct_return=True)
        self.results["output"] = open(self.logfile, "r").read()
        self._eval_execute()
        self._cleanup_system_exe()

        return self.results

    def execute5(self):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute5")

        exitcode = self.system(direct_return=True)

        if exitcode != 0:
            raise RuntimeError(f'system command\n{self.cmd}\nexitcode {exitcode}')

        self.results["exitcode"] = exitcode
        self.results["output"] = open(self.logfile, "r").read()
        self._eval_execute()
        self._cleanup_system_exe()

        return self.results

    def execute7(self):

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute7")

        self.run()

        return self.results

