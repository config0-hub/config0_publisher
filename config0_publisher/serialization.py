#!/usr/bin/env python

import json
import subprocess
import os
import pickle
import zlib
import gzip
import base64
import io

from io import StringIO
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

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

    return pickle.dump(obj=obj,
                       file=gzip.open(fname,
                                      "wb",
                                      compresslevel=3),
                       protocol=2)

def gz_upickle(fname):

    return pickle.load(gzip.open(fname,"rb"))

def zpickle(obj):

    return zlib.compress(pickle.dumps(obj,
                                      pickle.HIGHEST_PROTOCOL),
                         9)

def z_unpickle(zstr):
    return pickle.loads(zlib.decompress(zstr))

def compress(indata):

    return zlib.compress(indata,zlib.Z_BEST_COMPRESSION)

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

def encrypt_str(password, str_obj):

    salt = os.urandom(16)
    backend = default_backend()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=backend
    )
    key = kdf.derive(password.encode())

    iv = os.urandom(16)

    cipher = Cipher(algorithms.AES(key),
                    modes.CBC(iv),
                    backend=backend)

    encryptor = cipher.encryptor()

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(str_obj.encode()) + padder.finalize()

    ciphertext = encryptor.update(padded_data) + encryptor.finalize()

    # Convert byte code to string
    return (salt + iv + ciphertext).hex()

def decrypt_str(password, encrypted_str):

    # Convert string to byte code
    ciphertext = bytes.fromhex(encrypted_str)

    salt = ciphertext[:16]
    iv = ciphertext[16:32]
    ciphertext = ciphertext[32:]

    backend = default_backend()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
        backend=backend
    )
    key = kdf.derive(password.encode())

    cipher = Cipher(algorithms.AES(key),
                    modes.CBC(iv),
                    backend=backend)

    decryptor = cipher.decryptor()
    decrypted_data = decryptor.update(ciphertext) + decryptor.finalize()

    unpadder = padding.PKCS7(128).unpadder()
    unpadded_data = unpadder.update(decrypted_data) + unpadder.finalize()

    # Convert byte code to string
    return unpadded_data.decode()

def encrypt_str_openssl(password, str_obj):

    cmd = f'echo -n "{str_obj}" | openssl enc -e -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:{password} -base64'

    process = subprocess.Popen(cmd,
                               stdout=subprocess.PIPE,
                               shell=True)

    encrypted_output, _ = process.communicate()

    return encrypted_output.strip().decode()

def decrypt_str_openssl(password, encrypted_text):

    cmd = f'echo "{encrypted_text}" | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:{password} -base64'

    process = subprocess.Popen(cmd,
                               stdout=subprocess.PIPE,
                               shell=True)

    decrypted_output, _ = process.communicate()

    return decrypted_output.strip().decode()

def create_envfile(env_vars,envfile=None,secret=True):
    '''
    we use stateful_id for the encrypt key
    '''

    if not env_vars.items():
        return

    if not secret:

        file_obj = open(envfile,"w")

        for key,value in env_vars.items():
            file_obj.write(f"{key}={value}\n")
        file_obj.close()

        print(f"envfile {envfile} written.")

        return True

    # create encrypted string here
    virtual_file = StringIO()

    for key,value in env_vars.items():
        virtual_file.write(f"{key}={value}\n")

    # testtest456
    #print(virtual_file.getvalue())
    #encrypted_str = b64_encode(virtual_file.getvalue())

    # testtest456
    base64_string = b64_encode(virtual_file.getvalue())
    #encrypted_str = encrypt_str_openssl(secret,
    encrypted_str = encrypt_str_openssl("admin123",
                                        base64_string)

    print(encrypted_str)
    print(encrypted_str)
    print(encrypted_str)
    print(encrypted_str)
    raise Exception('test test')

    with open(envfile, 'w') as f:
        f.write(encrypted_str)

    print(f"encrypted envfile {envfile} written.")

    return encrypted_str
