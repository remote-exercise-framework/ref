#!/usr/bin/env python3.6

import argparse
import os
import subprocess
import sys

import requests
from colorama import Fore, Style
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

with open('/etc/instance_id', 'r') as f: # type: ignore
    INSTANCE_ID = int(f.read())

def finalize_request(req):
    signer = TimedSerializer(KEY, salt='from-container-to-web')
    req['instance_id'] = INSTANCE_ID
    req = signer.dumps(req)
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


def cmd_reset(_):
    print_warn('[!] This operation will revert all modifications.\n    All your data will be lost and you will have to start from scratch!\n    You have been warned.')
    print_warn('[!] Are you sure you want to continue? [y/n] ', end='')
    if not check_answer():
        exit(0)

    print_ok('[+] Resetting instance now. In case of success, you will be disconnected from the instance.', flush=True)
    req = {}
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/reset', json=req)
    handle_response(res)

def _run_tests():
    test_path = '/usr/local/bin/submission_tests'
    if not os.path.isfile(test_path):
        print_warn('[+] No testsuite found! Skipping tests..')
        return True

    ret = subprocess.run(test_path, shell=False, check=False)
    return ret.returncode == 0

def cmd_submit(_):
    print_ok('[+] Submitting instance..', flush=True)

    if not _run_tests():
        print_warn('[!] Failing tests may indicate that your solution is erroneous or not complete yet.')
        print_warn('[!] Are you sure you want to submit? [y/n] ', end='')
        if not check_answer():
            exit(0)
    else:
        print_ok('[+] Are you sure you want to submit? [y/n] ', end='')
        if not check_answer():
            exit(0)
    print_ok("[+] Submitting now. In case of success, you will be disconnected from the instance.", flush=True)
    req = {}
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/submit', json=req)
    handle_response(res)

def cmd_check(_):
    """
    Run a script that is specific to the current task and print its output?
    """
    _run_tests()

def cmd_id(_):
    print_ok(f'[+] If you need support, please provide this ID alongside your request.')
    print_ok(f'[+] Instance ID: {INSTANCE_ID}.')

def main():
    parser = argparse.ArgumentParser(prog="task")
    subparsers = parser.add_subparsers(dest='command')
    subparsers.required = True

    reset_parser = subparsers.add_parser('reset',
        help='Revert all modifications applied to your instance. WARNING: This cannot be undone; all user data will be lost permanently.'
        )
    reset_parser.set_defaults(func=cmd_reset)

    submit_parser = subparsers.add_parser('submit',
        help='Submit the current state of your work for grading. Your whole instance is submitted.'
        )
    submit_parser.set_defaults(func=cmd_submit)

    check_parser = subparsers.add_parser('check',
        help='Run various checks which verify whether your environment and submission match the solution.'
        )
    check_parser.set_defaults(func=cmd_check)

    check_parser = subparsers.add_parser('id',
        help='Get your instance ID. This ID is needed for all support requests.'
        )
    check_parser.set_defaults(func=cmd_id)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
