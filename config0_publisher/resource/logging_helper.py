import os
from config0_publisher.utilities import eval_str_to_join

class LoggingHelper:
    """
    Helper class for logging operations.
    """
    
    def __init__(self, logger, stateful_id=None):
        self.logger = logger
        self.stateful_id = stateful_id
        self.final_output = None
        
    def append_log(self, log):
        append = True

        if os.environ.get("JIFFY_LOG_FILE"):
            logfile = os.environ["JIFFY_LOG_FILE"]
        elif os.environ.get("CONFIG0_LOG_FILE"):
            logfile = os.environ["CONFIG0_LOG_FILE"]
        elif os.environ.get("LOG_FILE"):
            logfile = os.environ["LOG_FILE"]
        else:
            logfile = f"/tmp/{self.stateful_id}.log"
            append = False

        if isinstance(log, list) or eval_str_to_join(log):
            try:
                _str = "\n".join(log)
            except:
                _str = None
        else:
            _str = None

        if _str:
            output = _str
        else:
            output = log

        if append:
            with open(logfile, "a") as file:
                file.write("#"*32)
                file.write("\n# append log\n")
                file.write("#"*32)
                file.write("\n")
                file.write(output)
                file.write("\n")
                file.write("#"*32)
                file.write("\n")
        else:
            with open(logfile, "w") as file:
                file.write("#"*32)
                file.write("\n# append log\n")
                file.write("#"*32)
                file.write("\n")
                file.write(output)
                file.write("\n")
                file.write("#"*32)
                file.write("\n")

        return logfile
        
    def write_local_log(self):
        if not self.final_output:
            return False
            
        cli_log_file = f'/tmp/{self.stateful_id}.cli.log'

        with open(cli_log_file, "w") as f:
            f.write(self.final_output)

        print(f'local log file here: {cli_log_file}')

        return True
        
    @staticmethod
    def clean_output(results, replace=True):
        clean_lines = []

        if isinstance(results["output"], list):
            for line in results["output"]:
                try:
                    clean_lines.append(line.decode("utf-8"))
                except:
                    clean_lines.append(line)
        else:
            try:
                clean_lines.append((results["output"].decode("utf-8")))
            except:
                clean_lines.append(results["output"])

        if replace:
            results["output"] = "\n".join(clean_lines)

        return clean_lines
        
    def eval_log(self, results, local_log=None):
        if not results.get("output"):
            return

        self.clean_output(results, replace=True)
        self.final_output = results["output"]
        self.append_log(self.final_output)
        del results["output"]

        if local_log:
            try:
                self.write_local_log()
            except:
                self.logger.debug("could not write local log")

        print(self.final_output)
        
    def eval_failure(self, results, method, app_name=None, run_share_dir=None):
        if results.get("status") is not False:
            return

        self.eval_log(results)

        print("")
        print("-"*32)
        failed_message = f"{app_name} {method} failed here {run_share_dir}!"
        print(failed_message)
        print("-"*32)
        print("")
        exit(43)