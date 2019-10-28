#!/usr/bin/env python3.7

"""
This script acts as a replacement of the .authorized_keys file.
Hence, if a user tries to authenticate, this script is called and
expected to return a list of accepted public keys.
"""

import os
import sys
#TODO: This path is not part of the default path, fix the container! :-(
sys.path.append('/usr/local/lib/python3.7/site-packages')
import requests


def get_public_keys(username):
    req = {
        'username': username
    }

    #Get a list of all allowed public keys
    res = requests.post('http://web:8000/api/getkeys', json=req)
    keys = res.json()
    return keys['keys']

def main():
    
    keys = get_public_keys("")

    for k in keys:
        print(k)

if __name__ == "__main__":
    main()