#!/usr/bin/env python3.6

import argparse
import os
import socket
import subprocess
import sys
import time
import traceback

import requests
from colorama import Back, Fore, Style
from itsdangerous import TimedSerializer

sys.path.append('/usr/local/lib/python3.7/site-packages')

def print_ok(*args, **kwargs):
    print(Fore.GREEN, *args, Style.RESET_ALL, **kwargs, sep='')

def print_warn(*args, **kwargs):
    print(Fore.YELLOW, *args, Style.RESET_ALL, **kwargs, sep='')

def print_err(*args, **kwargs):
    print(Fore.RED, *args, Style.RESET_ALL, **kwargs, sep='')

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
        print_err('[!] Missing JSON body')
        return False
    except Exception:
        print_err('[!] Internal Error')
        return False
    else:
        if err != 200:
            if 'error' in json:
                print_err(f'[!] ', json['error'])
            else:
                print_err('[!] ', 'Unknown error! Please contact staff.')
            return False
        else:
            print_ok('[+] ', json)
    return True

def check_answer(prompt=None):
    if prompt:
        print(prompt, end='')
    data = input()
    data = data.lower()
    return data == 'y' or data == 'yes' or data == 'true'


def cmd_reset(args):
    print_ok('[+] This operation will revert all modifications. All your data will be lost and you will have to start from scratch! You have been warned.')
    print_ok('[+] Are you sure you want to continue? [y/n] ', end='')
    if not check_answer():
        exit(0)

    print_ok('[+] Resetting instance..', flush=True)
    req = {}
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/reset', json=req)
    handle_response(res)

def _run_tests():
    test_path = '/usr/local/bin/submission-tests'
    if not os.path.isfile(test_path):
        print_warn('[+] No testsuite found! Skipping tests..')
        return True

    ret = subprocess.run(test_path, shell=False, check=False)
    return ret.returncode == 0

def cmd_submit(args):
    print_ok('[+] Submitting instance..', flush=True)

    if not _run_tests():
        print_warn('[!] Some tests failed. This can indicate that your solution is erroneous or not complete yet.')
        print_warn('[!] Are you sure you want to submit? [y/n] ', end='')
        if not check_answer():
            exit(0)

    req = {}
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/submit', json=req)
    handle_response(res)

def cmd_presubmit(args):
    """
    Run a script that is specific to the current task and print its output?
    """
    _run_tests()

def cmd_id(args):
    print_ok(f'[+] The current container ID is {INSTANCE_ID}.')
    print_ok(f'[+] If you need support, please provide this ID alongside your request.')

def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    subparsers.required = True
    
    reset_parser = subparsers.add_parser('reset', 
        help='Revert all modifications applied to your container instance. WARNING: This cannot be undone; all user data will be lost permanently.'
        )
    reset_parser.set_defaults(func=cmd_reset)

    submit_parser = subparsers.add_parser('submit', 
        help='Submit the current state of your work for grading. Your whole container is submitted.'
        )
    submit_parser.set_defaults(func=cmd_submit)

    presubmit_parser = subparsers.add_parser('presubmit', 
        help='Run various checks which verify whether your environment and submission match the solution.'
        )
    presubmit_parser.set_defaults(func=cmd_presubmit)

    presubmit_parser = subparsers.add_parser('id',
        help='Get your container instance ID. This ID is needed for all support requests.'
        )
    presubmit_parser.set_defaults(func=cmd_id)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
