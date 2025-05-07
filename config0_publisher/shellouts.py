#!/usr/bin/env python

import concurrent.futures
import json
import string
import os
import random
import subprocess
from config0_publisher.loggerly import Config0Logger as set_log


def ensure_str(obj, strip=True):
    """Convert object to string and optionally strip whitespace."""
    if not isinstance(obj, str):
        try:
            new_obj = obj.decode("utf-8") if isinstance(obj, bytes) else obj
        except Exception:
            new_obj = obj
    else:
        new_obj = obj

    if strip and isinstance(new_obj, str):
        return new_obj.strip()

    return new_obj


def mkdir(directory):
    """Create a directory and any necessary parent directories."""
    try:
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        return True
    except Exception as e:
        print(f"Error creating directory {directory}: {e}")
        return False


def rm_rf(location):
    """Uses the shell to forcefully and recursively remove a file/entire directory."""
    if not location or not os.path.exists(location):
        return True

    try:
        os.remove(location)
        return True
    except Exception:
        pass

    try:
        os.system(f"rm -rf {location} > /dev/null 2>&1")
        return not os.path.exists(location)
    except Exception:
        print(f"Problems with removing {location}")
        return False


def execute3(cmd, **kwargs):
    """Execute a command with ShellOutExecute and handle output."""
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
    """Alias for execute3."""
    return execute3(cmd, **kwargs)


def execute3a(cmd, **kwargs):
    """Execute a command with system and handle output."""
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
    """Alias for execute3a."""
    return execute3a(cmd, **kwargs)


def execute5(cmd, **kwargs):
    """Execute a command with system and raise exception on error."""
    shellout_exe = ShellOutExecute(cmd,
                                   unbuffered=None,
                                   **kwargs)

    shellout_exe.execute5()

    if kwargs.get("exit_error"):
        exit(shellout_exe.results["exitcode"])

    return shellout_exe.results


def execute7(cmd, **kwargs):
    """Execute a command using run method."""
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
    """Execute a shell command, returning status, stdout, and stderr."""
    inputargs = {"unbuffered": unbuffered}

    if logfile:
        inputargs["logfile"] = logfile
        inputargs["write_logfile"] = True

    shellout_exe = ShellOutExecute(cmd, **inputargs)
    shellout_exe.popen2()

    if print_out and unbuffered:
        shellout_exe.print_out()

    return shellout_exe.results["exitcode"], shellout_exe.results["stdout"], shellout_exe.results["stderr"]


class ShellOutExecute:
    """Handles shell command execution with various methods and output collection."""
    
    def __init__(self, cmd, unbuffered=None, **kwargs):
        """Initialize the shell execution object."""
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
            try:
                self.logfile_handle = open(self.logfile, "w")
            except Exception as e:
                self.logger.error(f"Failed to open logfile {self.logfile}: {e}")

        self.results = {
            "status": None,
            "failed_message": None,
            "output": None,
            "exitcode": None,
            "stdout": None,
            "stderr": None
        }

    @staticmethod
    def _id_generator(size=6, chars=string.ascii_uppercase + string.digits):
        """Generate a random ID of specified size using the given character set."""
        return ''.join(random.choice(chars) for _ in range(size))

    def _set_cwd(self):
        """Set the current working directory."""
        try:
            self.cwd = os.getcwd()
        except Exception:
            self.logger.warn("Cannot determine current directory - setting cwd to /tmp")
            self.cwd = "/tmp"
            try:
                os.chdir(self.cwd)
            except Exception as e:
                self.logger.error(f"Failed to change directory to {self.cwd}: {e}")

        return self.cwd

    def _get_system_cmd(self):
        """Create a command string that captures output and exit code."""
        cmd = f'({self.cmd} 2>&1 ; echo $? > {self.exit_file}) | tee -a {self.logfile}; exit `cat {self.exit_file}`'
        return cmd

    def _cleanup_system_exe(self):
        """Remove temporary files."""
        try:
            if os.path.exists(self.exit_file):
                os.remove(self.exit_file)
            if os.path.exists(self.logfile):
                os.remove(self.logfile)
        except Exception as e:
            self.logger.warn(f"Failed to clean up temporary files: {e}")

    def add_unset_envs_to_cmd(self):
        """Add commands to unset environment variables to the command string."""
        if not self.unset_envs:
            return

        unset_envs = [_element.strip() for _element in self.unset_envs.split(",")]
        for _env in unset_envs:
            self.cmd = f"unset {_env}; {self.cmd}"

    def set_env_vars(self):
        """Set environment variables for command execution."""
        if not self.env_vars:
            return

        try:
            _env_vars = self.env_vars.get()
        except Exception as e:
            self.logger.error(f"Failed to get environment variables: {e}")
            return

        for ek, ev in _env_vars.items():
            try:
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
            except Exception as e:
                self.logger.error(f"Failed to set environment variable {ek}: {e}")

        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug("#" * 32)
            self.logger.debug("# env vars set are")
            try:
                print(json.dumps(self.env_vars_set, sort_keys=True, indent=4))
            except Exception:
                self.logger.error("Failed to print environment variables")
            self.logger.debug("#" * 32)

        return _env_vars

    def print_out(self):
        """Print command output."""
        if not self.results:
            return

        output = self.results.get("output")
        if not output:
            return

        try:
            self.logger.debug(output)
        except Exception:
            print(output)

    def _convert_output_to_json(self):
        """Convert string output to JSON if possible."""
        if not self.output_to_json:
            return

        if isinstance(self.results["output"], dict):
            return

        try:
            output = json.loads(self.results["output"])
            self.results["output"] = output
            return True
        except Exception:
            if os.environ.get("JIFFY_ENHANCED_LOG"):
                self.logger.debug("Could not convert output to json")
            return

    def _eval_execute(self):
        """Evaluate execution results and update status."""
        if self.results["exitcode"] != 0:
            self.results["status"] = False
            self.results["failed_message"] = self.results["output"]
        else:
            self.results["status"] = True
            self._convert_output_to_json()

        if self.output_queue:
            try:
                self.output_queue.put(self.results)
            except Exception:
                self.logger.error("Could not append the results to the output_queue")

    def set_popen_kwargs(self):
        """Set keyword arguments for subprocess.Popen."""
        self.popen_kwargs = {
            "shell": True,
            "universal_newlines": True,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT
        }

    def run(self):
        """Run command using subprocess.run."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: run")

        self.set_env_vars()
        self.set_popen_kwargs()

        try:
            process = subprocess.run(self.cmd, **self.popen_kwargs)
            self.results["output"] = process.stdout
            self._add_log_file(self.results["output"])
            self.results["exitcode"] = self._eval_exitcode(process.returncode)
        except Exception as e:
            self.logger.error(f"Error running command: {e}")
            self.results["exitcode"] = 1
            self.results["output"] = str(e)

        self._eval_execute()
        return self.results

    def _init_popen(self):
        """Initialize subprocess.Popen process."""
        try:
            return subprocess.Popen(self.cmd, **self.popen_kwargs)
        except Exception as e:
            self.logger.error(f"Failed to initialize process: {e}")
            raise

    def _add_log_file(self, line):
        """Add output line to log file."""
        if not self.logfile_handle:
            return

        try:
            self.logfile_handle.write(line)
            self.logfile_handle.write("\n")
        except Exception as e:
            self.logger.error(f"Failed to write to log file: {e}")

    def _eval_log_line(self, readline, lines):
        """Process a line of output."""
        try:
            line = ensure_str(readline, strip=True)
            if not line:
                return

            lines.append(line)

            if self.unbuffered:
                print(line)

            self._add_log_file(line)
            return True
        except Exception as e:
            self.logger.error(f"Error processing log line: {e}")
            return False

    def _eval_popen_exe(self, process):
        """Process output from a running subprocess."""
        lines = []

        try:
            while True:
                readline = process.stdout.readline()
                self._eval_log_line(readline, lines)

                exitcode = process.poll()
                if exitcode is not None:
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
            self.results["status"] = exitcode == 0
        except Exception as e:
            self.logger.error(f"Error evaluating process output: {e}")
            self.results["exitcode"] = 1
            self.results["status"] = False
            self.results["output"] = str(e)

        self._eval_execute()

    def _popen_communicate(self, process):
        """Communicate with subprocess and capture output."""
        try:
            out, err = process.communicate()
            self.results["stdout"] = out
            self.results["stderr"] = err
            self.results["exitcode"] = self._eval_exitcode(process.returncode)
        except Exception as e:
            self.logger.error(f"Error communicating with process: {e}")
            self.results["exitcode"] = 1
            self.results["stdout"] = ""
            self.results["stderr"] = str(e)

        return self.results

    def popen(self):
        """Execute command using Popen with streaming output."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: popen")

        self.set_popen_kwargs()
        self.popen_kwargs["bufsize"] = 0

        try:
            process = self._init_popen()
            self._eval_popen_exe(process)
        except Exception as e:
            self.logger.error(f"Error in popen execution: {e}")
            self.results["exitcode"] = 1
            self.results["output"] = str(e)
            self.results["status"] = False

        return self.results

    def popen2(self):
        """Execute command using Popen with separate stdout and stderr capture."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: popen2")

        try:
            process = subprocess.Popen(
                self.cmd,
                shell=True,
                universal_newlines=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            self._popen_communicate(process)
        except Exception as e:
            self.logger.error(f"Error in popen2 execution: {e}")
            self.results["exitcode"] = 1
            self.results["stdout"] = ""
            self.results["stderr"] = str(e)
            self.results["status"] = False

        return self.results

    def execute6(self):
        """Execute with environment handling and popen."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute6")

        self.logger.debug(f"from directory {os.getcwd()} - command {self.cmd}")

        self.set_env_vars()
        self.add_unset_envs_to_cmd()

        return self.popen()

    def execute3(self):
        """Execute with environment handling and simple popen."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute3")

        self.logger.debug(f"from directory {os.getcwd()} - command {self.cmd}")

        self.set_env_vars()
        self.popen()

        return self.results

    def system(self, direct_return=True):
        """Execute command using os.system capturing output to file."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: system")

        cmd = self._get_system_cmd()
        try:
            _return_code = os.system(cmd)
        except Exception as e:
            self.logger.error(f"Error executing system command: {e}")
            return 1

        if direct_return:
            return self._eval_exitcode(_return_code)

        # Calculate the return value code
        try:
            return int(bin(_return_code).replace("0b", "").rjust(16, '0')[:8], 2)
        except Exception:
            return _return_code

    @staticmethod
    def _eval_exitcode(exitcode):
        """Convert exitcode to integer if possible."""
        try:
            return int(exitcode)
        except Exception:
            return exitcode

    def execute3a(self):
        """Execute with system and file-based output capture."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute3a")

        self.results["exitcode"] = self.system(direct_return=True)
        try:
            with open(self.logfile, "r") as f:
                self.results["output"] = f.read()
        except Exception as e:
            self.logger.error(f"Failed to read logfile: {e}")
            self.results["output"] = f"Error reading output: {e}"

        self._eval_execute()
        self._cleanup_system_exe()

        return self.results

    def execute5(self):
        """Execute with system and raise exception on error."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute5")

        exitcode = self.system(direct_return=True)

        if exitcode != 0:
            raise RuntimeError(f'system command\n{self.cmd}\nexitcode {exitcode}')

        try:
            with open(self.logfile, "r") as f:
                self.results["output"] = f.read()
        except Exception as e:
            self.logger.error(f"Failed to read logfile: {e}")
            self.results["output"] = f"Error reading output: {e}"

        self.results["exitcode"] = exitcode
        self._eval_execute()
        self._cleanup_system_exe()

        return self.results

    def execute7(self):
        """Execute using run method."""
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            self.logger.debug_highlight("ShellOutExecute:::method: execute7")

        self.run()
        return self.results