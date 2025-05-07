#!/usr/bin/env python

from config0_publisher.utilities import to_json


def convert_config0_output_to_values(output):
    """
    Extract and convert config0 output values to JSON format.
    
    Args:
        output: The raw output string from config0
        
    Returns:
        JSON object parsed from the extracted output
    """
    record_on = None
    values = []

    if not output:
        print("ERROR: Output is None or empty")
        exit(9)

    try:
        for line in output.split("\n"):
            if not line:
                continue

            if "_config0_begin_output" in line:
                record_on = True
                continue

            if "_config0_end_output" in line:
                record_on = None
                continue

            if not record_on:
                continue

            values.append(line)

        if not values:
            print("ERROR: No values found between config0 output markers")
            exit(9)

        obj_return = "\n".join(values) if len(values) > 1 else values[0]

        try:
            return to_json(obj_return)
        except Exception as e:
            print(f"ERROR: Cannot convert to json: {str(e)}")
            exit(9)
            
    except Exception as e:
        print(f"ERROR: Failed to process output: {str(e)}")
        exit(9)