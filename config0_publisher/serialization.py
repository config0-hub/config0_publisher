#!/usr/bin/env python

import os
import io
import json
import gzip
import zlib
import pickle
import base64
import subprocess
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import modes
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.fernet import Fernet


def compress_and_encode_dict(data):
    """Compress and base64 encode a dictionary"""
    try:
        json_string = json.dumps(data)
        compressed_data = zlib.compress(json_string.encode('utf-8'))
        base64_encoded_data = base64.b64encode(compressed_data)
        return base64_encoded_data.decode('utf-8')
    except Exception as e:
        raise ValueError(f"Failed to compress and encode dictionary: {e}")


def decode_and_decompress_string(encoded_str):
    """Decode a base64 string and decompress it to a dictionary"""
    try:
        compressed_data = base64.b64decode(encoded_str)
        json_string = zlib.decompress(compressed_data).decode('utf-8')
        return json.loads(json_string)
    except Exception as e:
        raise ValueError(f"Failed to decode and decompress string: {e}")


def convert_to_fernet_key(key):
    """Convert a string key to a valid Fernet key"""
    try:
        padded_key = key.ljust(32, "\x00")
        key_bytes = padded_key.encode()
        base64_key = base64.urlsafe_b64encode(key_bytes)
        return base64_key
    except Exception as e:
        raise ValueError(f"Failed to convert key to Fernet key: {e}")


def encrypt_file(secret, input_file=None, file_content=None, output_file=None):
    """Encrypt file content using Fernet encryption"""
    try:
        passphrase = convert_to_fernet_key(secret)

        if input_file:
            try:
                with open(input_file, 'rb') as file:
                    file_content = file.read()
            except IOError as e:
                raise IOError(f"Failed to read input file {input_file}: {e}")

        if file_content:
            base64_content = base64.b64encode(file_content.encode() if isinstance(file_content, str) else file_content)
        else:
            raise ValueError("No content to encrypt")

        cipher_suite = Fernet(passphrase)
        encrypted_content = cipher_suite.encrypt(base64_content)

        if not output_file:
            return encrypted_content

        try:
            with open(output_file, 'wb') as file:
                file.write(encrypted_content)
            return encrypted_content
        except IOError as e:
            raise IOError(f"Failed to write to output file {output_file}: {e}")
    except Exception as e:
        raise RuntimeError(f"Encryption failed: {e}")


def decrypt_file(input_file, output_file, secret):
    """Decrypt a file using Fernet decryption"""
    try:
        passphrase = convert_to_fernet_key(secret)

        try:
            with open(input_file, 'rb') as file:
                encrypted_content = file.read()
        except IOError as e:
            raise IOError(f"Failed to read input file {input_file}: {e}")

        cipher_suite = Fernet(passphrase)
        decrypted_content = cipher_suite.decrypt(encrypted_content)
        base64_content = base64.b64decode(decrypted_content)

        try:
            with open(output_file, 'wb') as file:
                file.write(base64_content)
        except IOError as e:
            raise IOError(f"Failed to write to output file {output_file}: {e}")
    except Exception as e:
        raise RuntimeError(f"Decryption failed: {e}")


def b64_encode(obj):
    """Base64 encode an object or string"""
    try:
        if not isinstance(obj, str):
            obj = json.dumps(obj)
        
        _bytes = obj.encode('ascii')
        base64_bytes = base64.b64encode(_bytes)
        return base64_bytes.decode('ascii')
    except Exception as e:
        raise ValueError(f"Failed to base64 encode object: {e}")


def b64_decode(token):
    """Base64 decode a token with multiple fallback decoding attempts"""
    try:
        base64_bytes = token.encode('ascii')
        _bytes = base64.b64decode(base64_bytes)

        # Try several decoding methods in sequence
        try:
            _results = json.loads(_bytes.decode('ascii'))
            return _results
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass

        try:
            _results = _bytes.decode('ascii')
            if _results:
                return _results
        except UnicodeDecodeError:
            pass

        try:
            _results = _bytes.decode()
            if _results:
                return _results
        except UnicodeDecodeError:
            pass

        # Final fallback
        return _bytes.decode("utf-8")
    except Exception as e:
        raise ValueError(f"Failed to base64 decode token: {e}")


def gz_pickle(fname, obj):
    """Pickle and compress an object to a file"""
    try:
        with gzip.open(fname, "wb", compresslevel=3) as f:
            return pickle.dump(obj=obj, file=f, protocol=2)
    except Exception as e:
        raise IOError(f"Failed to pickle and compress object to {fname}: {e}")


def gz_upickle(fname):
    """Load a pickled and compressed object from a file"""
    try:
        with gzip.open(fname, "rb") as f:
            return pickle.load(f)
    except Exception as e:
        raise IOError(f"Failed to load pickled and compressed object from {fname}: {e}")


def compress(indata):
    """Compress data using zlib with best compression"""
    try:
        return zlib.compress(indata, zlib.Z_BEST_COMPRESSION)
    except Exception as e:
        raise ValueError(f"Failed to compress data: {e}")


def uncompress(zdata):
    """Decompress zlib compressed data"""
    try:
        return zlib.decompress(zdata)
    except Exception as e:
        raise ValueError(f"Failed to decompress data: {e}")


def create_envfile(dict_obj, b64=None, file_path=None):
    """Create an environment file from a dictionary"""
    try:
        file_buffer = io.StringIO()

        for _k, _v in list(dict_obj.items()):
            file_buffer.write(f"{_k}={_v}\n")

        contents = file_buffer.getvalue()
        file_buffer.close()

        if not b64 and not file_path:
            return contents

        if not b64:
            try:
                with open(file_path, 'w') as file:
                    file.write(contents)
                return contents
            except IOError as e:
                raise IOError(f"Failed to write to file {file_path}: {e}")

        base64_hash = base64.b64encode(contents.encode()).decode()

        if not file_path:
            return base64_hash

        try:
            with open(file_path, 'w') as file:
                file.write(base64_hash)
            return base64_hash
        except IOError as e:
            raise IOError(f"Failed to write to file {file_path}: {e}")
    except Exception as e:
        raise RuntimeError(f"Failed to create environment file: {e}")


def encrypt_str(password, str_obj):
    """Encrypt a string using AES-CBC with PBKDF2"""
    try:
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
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        encryptor = cipher.encryptor()
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(str_obj.encode()) + padder.finalize()
        ciphertext = encryptor.update(padded_data) + encryptor.finalize()
        return (salt + iv + ciphertext).hex()
    except Exception as e:
        raise ValueError(f"Failed to encrypt string: {e}")


def decrypt_str(password, encrypted_str):
    """Decrypt a string that was encrypted with AES-CBC and PBKDF2"""
    try:
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
        
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=backend)
        decryptor = cipher.decryptor()
        decrypted_data = decryptor.update(ciphertext) + decryptor.finalize()
        
        unpadder = padding.PKCS7(128).unpadder()
        unpadded_data = unpadder.update(decrypted_data) + unpadder.finalize()
        
        return unpadded_data.decode()
    except Exception as e:
        raise ValueError(f"Failed to decrypt string: {e}")


def encrypt_str_openssl(password, str_obj):
    """Encrypt a string using OpenSSL AES-256-CBC"""
    try:
        cmd = f'echo -n "{str_obj}" | openssl enc -e -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:{password} -base64'
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        encrypted_output, _ = process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"OpenSSL encryption failed with return code {process.returncode}")
            
        return encrypted_output.strip().decode()
    except Exception as e:
        raise RuntimeError(f"Failed to encrypt string using OpenSSL: {e}")


def decrypt_str_openssl(password, encrypted_text):
    """Decrypt a string using OpenSSL AES-256-CBC"""
    try:
        cmd = f'echo "{encrypted_text}" | openssl enc -d -aes-256-cbc -pbkdf2 -iter 100000 -pass pass:{password} -base64'
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        decrypted_output, _ = process.communicate()
        
        if process.returncode != 0:
            raise RuntimeError(f"OpenSSL decryption failed with return code {process.returncode}")
            
        return decrypted_output.strip().decode()
    except Exception as e:
        raise RuntimeError(f"Failed to decrypt string using OpenSSL: {e}")


def create_encrypted_envfile(env_vars, secret, file_path, openssl=True):
    """Create an encrypted environment file using either OpenSSL or Fernet"""
    try:
        if not env_vars.items():
            return None
            
        virtual_file = io.StringIO()
        
        for key, value in env_vars.items():
            virtual_file.write(f"{key}={value}\n")
            
        base64_string = b64_encode(virtual_file.getvalue())
        
        if openssl:
            encrypted_content = encrypt_str_openssl(secret, base64_string)
            try:
                with open(file_path, 'w') as f:
                    f.write(encrypted_content)
            except IOError as e:
                raise IOError(f"Failed to write to file {file_path}: {e}")
        else:
            encrypted_content = encrypt_file(secret, file_content=base64_string, output_file=file_path)
            
        print(f"encrypted file_path {file_path}/openssl {openssl} written.")
        print(f"decrypted file_path {file_path} written.")
        
        return encrypted_content
    except Exception as e:
        raise RuntimeError(f"Failed to create encrypted environment file: {e}")