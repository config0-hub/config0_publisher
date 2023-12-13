from config0_publisher.utilities import to_json

def convert_config0_output_to_values(output):

    record_on = None
    values = []

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
        print('ERROR: values is None/empty')
        exit(9)

    if len(values) > 1:
        obj_return = "\n".join(values)
    elif len(values) == 1:
        obj_return = values[0]

    try:
        obj_return = to_json(obj_return)
    except:
        print('ERROR: Cannot convert to json')
        exit(9)

    return obj_return
