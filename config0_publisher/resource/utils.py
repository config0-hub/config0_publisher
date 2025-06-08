import json
import os
from pathlib import Path
from config0_publisher.utilities import to_json

def to_jsonfile(values, filename, exec_dir=None):
    """
    Write values to a JSON file in the config0_resources directory.
    """
    if not exec_dir: 
        exec_dir = os.getcwd()

    file_dir = os.path.join(exec_dir, "config0_resources")
    file_path = os.path.join(file_dir, filename)

    # Create directory if it doesn't exist
    Path(file_dir).mkdir(parents=True, exist_ok=True)

    try:
        with open(file_path, "w") as file:
            file.write(json.dumps(values))
        status = True
        print(f"Successfully wrote contents to {file_path}")
    except:
        print(f"Failed to write contents to {file_path}")
        status = False

    return status

def to_json_object(output):
    """Convert output to JSON object if it's not already a dict."""
    if isinstance(output, dict):
        return output

    try:
        _output = to_json(output)
        if not _output:
            raise Exception("output is None")
        if not isinstance(_output, dict):
            raise Exception("output is not a dict")
        output = _output
    except:
        if os.environ.get("JIFFY_ENHANCED_LOG"):
            print("Could not convert output to json")

    return output