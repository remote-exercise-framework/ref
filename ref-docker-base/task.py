#!/usr/bin/env python3.6

import argparse
import os
import socket
import sys
import time
import traceback

import requests
from itsdangerous import TimedSerializer

sys.path.append('/usr/local/lib/python3.7/site-packages')

with open('/etc/key', 'rb') as f:
    KEY = f.read()

with open('/etc/instance_id', 'r') as f:
    INSTANCE_ID = int(f.read())

def finalize_request(req):
    s = TimedSerializer(KEY, salt='from-container-to-web')
    req['instance_id'] = INSTANCE_ID
    req = s.dumps(req)
    return req

def handle_response(resp):
    try:
        err = resp.status_code
        json = resp.json()
    except ValueError:
        print('Missing JSON body')
        return False
    except Exception:
        print('Internal Error')
        return False
    else:
        if err != 200:
            if 'error' in json:
                print(json['error'])
            else:
                print('Unknown error, please contact the staff.')
            return False
        else:
            print(json)
    return True

def check_answer(prompt=None):
    data = input(prompt)
    data = data.lower()
    return data == 'y' or data == 'yes' or data == 'true'


def cmd_reset(args):
    print('This operation will delete all data of this instance!')
    if not check_answer('Continue [y/n]'):
        exit(0)

    print('Resetting instance...', flush=True)
    req = {}
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/reset', json=req)
    handle_response(res)

def cmd_submit(args):
    print('Submitting instance...', flush=True)

    req = {}
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/submit', json=req)
    handle_response(res)

def cmd_presubmit(args):
    """
    Run a script that is specific to the current task and print its output?
    """
    pass

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    subparsers.required = True
    
    reset_parser = subparsers.add_parser('reset', 
        help='Revert all modifications applied to this instance.'
        )
    reset_parser.set_defaults(func=cmd_reset)

    submit_parser = subparsers.add_parser('submit', 
        help='Submit the current state of the instance for grading.'
        )
    submit_parser.set_defaults(func=cmd_submit)

    presubmit_parser = subparsers.add_parser('presubmit', 
        help='Run sanity checks for the current task and provied feedback whether it is working as expected.'
        )
    presubmit_parser.set_defaults(func=cmd_presubmit)


    args = parser.parse_args()
    print(args)
    args.func(args)

if __name__ == "__main__":
    main()
