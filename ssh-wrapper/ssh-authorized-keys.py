#!/usr/local/bin/python3.9

"""
This script acts as a replacement for the .authorized_keys file.
Hence, if a user tries to authenticate, this script is called and
expected to return a list of accepted public keys.
"""

import os
import sys
#TODO: This path is not part of the default path, fix the container! :-(
sys.path.append('/usr/local/lib/python3.9/site-packages')
import requests
from itsdangerous import Serializer

#Key used to sign messages send to the webserver
with open('/etc/request_key', 'rb') as f:
    SECRET_KEY = f.read()

def get_public_keys(username):
    req = {
        'username': username
    }

    s = Serializer(SECRET_KEY)
    req = s.dumps(req)

    #Get a list of all allowed public keys
    res = requests.post('http://web:8000/api/getkeys', json=req)
    keys = res.json()

    return keys['keys']

def main():
    keys = get_public_keys("NotUsed")

    #OpenSSH expects the keys to be printed to stdout
    for k in keys:
        print(k)

if __name__ == "__main__":
    main()