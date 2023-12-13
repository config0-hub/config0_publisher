#!/usr/bin/env python

import json
import pickle
import zlib
import gzip
import base64
import hashlib
import io

def b64_encode(obj):

    if not isinstance(obj,str):
        obj = json.dumps(obj)

    _bytes = obj.encode('ascii')
    base64_bytes = base64.b64encode(_bytes)

    # decode the b64 binary in a b64 string
    return base64_bytes.decode('ascii')

def b64_decode(token):

    base64_bytes = token.encode('ascii')
    _bytes = base64.b64decode(base64_bytes)

    try:
        _results = json.loads(_bytes.decode('ascii'))
    except:
        _results = _bytes.decode('ascii')

    return _results

def gz_pickle(fname, obj):
    return pickle.dump(obj=obj,file=gzip.open(fname,"wb",compresslevel=3),protocol=2)

def gz_upickle(fname):
    return pickle.load(gzip.open(fname,"rb"))

def zpickle(obj):
    return zlib.compress(pickle.dumps(obj,pickle.HIGHEST_PROTOCOL),9)

def z_unpickle(zstr):
    return pickle.loads(zlib.decompress(zstr))

def compress(indata):
    outdata = zlib.compress(indata,zlib.Z_BEST_COMPRESSION)
    return outdata

def uncompress(zdata):
    return zlib.decompress(zdata)  

# dup 452346236234
def to_envfile(obj,b64=True):

    # Create a StringIO object
    file_buffer = io.StringIO()

    for _k,_v in list(obj.items()):
        file_buffer.write("export {}={}\n".format(_k,_v))

    if not b64:
        return file_buffer.getvalue()
    
    base64_hash = base64.b64encode(file_buffer.getvalue().encode()).decode()
    
    # Close the StringIO object
    file_buffer.close()

    return base64_hash
