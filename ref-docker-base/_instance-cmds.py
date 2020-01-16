#!/usr/bin/env python3.6

import os
import time
import socket
import traceback
import sys
sys.path.append('/usr/local/lib/python3.7/site-packages')
import requests
from itsdangerous import TimedSerializer

with open('/etc/key', 'rb') as f:
    KEY = f.read()

with open('/etc/instance_id', 'r') as f:
    INSTANCE_ID = int(f.read())

def finalize_request(req):
    s = TimedSerializer(KEY, salt='from-container-to-web')
    req['instance_id'] = INSTANCE_ID
    req = s.dumps(req)
    return req

def request_instance_reset():
    req = {}
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/reset', json=req)

    try:
        json = res.json()
        return 200, json
    except ValueError:
        return 400, 'Missing JSON body'
    except Exception:
        return 400, 'Internal Error'

def main():
    if len(sys.argv) < 2:
        print("Not enough argument!")
        exit(1)

    cmd = sys.argv[1]

    if cmd == "reset":
        print(request_instance_reset())
    else:
        print("Unknown command")
        exit(1)

if __name__ == "__main__":
    main()
