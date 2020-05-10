#!/usr/bin/env python3.6

import argparse
import os
import subprocess
import sys
import typing

import requests
from itsdangerous import TimedSerializer

from ref_utils import print_err, print_ok, print_warn

with open('/etc/key', 'rb') as f:
    KEY = f.read()

with open('/etc/instance_id', 'r') as f: # type: ignore
    INSTANCE_ID = int(f.read())

def finalize_request(req):
    signer = TimedSerializer(KEY, salt='from-container-to-web')
    req['instance_id'] = INSTANCE_ID
    req = signer.dumps(req)
    return req

def handle_response(resp, expected_status=(200, )) -> typing.Tuple[int, typing.Dict]:
    """
    Process a response of a "requests" request.
    If the response has a status code not in expected_status,
    the program is terminated and an error message is displayed
    to the user. If the status code is in expected_status and the
    response contains a JSON body, a tuple status_code, json_body
    is returned.
    """
    status_code = resp.status_code
    json = None

    json_error = None
    try:
        json = resp.json()
    except ValueError:
        json_error = f'[!] Missing JSON body (status={status_code})'
    except Exception:
        json_error = f'[!] Internal Error (status={status_code})'

    if json_error:
        #Answers always have to contain JSON
        print_err(json_error)
        exit(1)

    if status_code in expected_status:
        return status_code, json
    else:
        if 'error' in json:
            print_err(f'[!] ', json['error'])
        else:
            print_err(f'[!] ', 'Unknown error! Please contact the staff')
        exit(1)

def check_answer(prompt=None):
    if prompt:
        print(prompt, end='')
    try:
        data = input()
    except EOFError:
        print_err('[!] No answer provided, exiting.')
        exit(1)
    data = data.lower()
    return data in ['y', 'yes', 'true']


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
        return 0, 'No testsuit found'

    log_path = '/tmp/test_logfile'
    with open(log_path, 'w') as logfile:
        proc = subprocess.Popen(test_path, shell=False, universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in proc.stdout:
            sys.stdout.write(line)
            logfile.write(line)
        proc.wait()

    return proc.returncode == 0, open(log_path, 'r').read()

def cmd_submit(_):
    print_ok('[+] Submitting instance..', flush=True)

    ret, out = _run_tests()
    if ret != 0:
        print_warn('[!] Failing tests may indicate that your solution is erroneous or not complete yet.')
        print_warn('[!] Are you sure you want to submit? [y/n] ', end='')
        if not check_answer():
            exit(0)
    else:
        print_ok('[+] Are you sure you want to submit? [y/n] ', end='')
        if not check_answer():
            exit(0)
    print_ok("[+] Submitting now. In case of success, you will be disconnected from the instance.", flush=True)
    req = {
        'test_log': out,
        'test_ret': ret
    }
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
    print_ok(f'[+] Instance ID: {INSTANCE_ID}')

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

    id_parser = subparsers.add_parser('id',
        help='Get your instance ID. This ID is needed for all support requests.'
        )
    id_parser.set_defaults(func=cmd_id)

    # diff_parser = subparsers.add_parser('diff',
    #     help='Get your instance ID. This ID is needed for all support requests.'
    #     )
    # diff_parser.set_defaults(func=cmd_diff)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
