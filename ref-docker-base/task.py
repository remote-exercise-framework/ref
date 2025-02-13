#!/usr/bin/env python3

import argparse
import json
import os
import subprocess
import sys
import typing as ty
import shutil
from pathlib import Path
from dataclasses import asdict, dataclass

import requests
from itsdangerous import TimedSerializer

from ref_utils import print_err, print_ok, print_warn

# ! Keep in sync with _TestResult in ref_utils/decorator.py
@dataclass
class TestResult():
    """
    The result of an submission test.
    """
    name: str
    success: bool
    score: ty.Optional[float]

# ! Keep in sync with ref_utils/decorator.py
TEST_RESULT_PATH = Path("/var/test_result")

with open('/etc/key', 'rb') as f:
    KEY = f.read()

with open('/etc/instance_id', 'r') as f: # type: ignore
    INSTANCE_ID = int(f.read())

IS_SUBMISSION = os.path.isfile('/etc/is_submission')
MAX_TEST_OUTPUT_LENGTH = 10000

def finalize_request(req):
    signer = TimedSerializer(KEY, salt='from-container-to-web')
    req['instance_id'] = INSTANCE_ID
    req = signer.dumps(req)
    return req

def handle_response(resp, expected_status=(200, )) -> ty.Tuple[int, ty.Dict]:
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
            print_err(f'[!]', json['error'])
        else:
            print_err(f'[!]', 'Unknown error! Please contact the staff')
        exit(1)

def user_answered_yes(prompt=None):
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
    if not user_answered_yes():
        exit(0)

    print_ok('[+] Resetting instance now. In case of success, you will be disconnected from the instance.', flush=True)
    req = {}
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/reset', json=req)
    handle_response(res)

def _run_tests() ->  ty.Tuple[str, ty.List[TestResult]]:
    test_path = '/usr/local/bin/submission_tests'
    if not os.path.isfile(test_path):
        print_warn('[+] No testsuite found! Skipping tests..')
        return "No testsuite found! Skipping tests..", []

    output_log_path = Path('/tmp/test_logfile')
    with output_log_path.open("w") as output_logfile:
        proc = subprocess.Popen(test_path, shell=False, universal_newlines=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        assert proc.stdout
        for line in proc.stdout:
            sys.stdout.write(line)
            output_logfile.write(line)
        proc.wait()

    if not TEST_RESULT_PATH.exists():
        print_err("[!] The submission test did not produce any output, this should not happend! Please ask for assistance.")
        exit(1)

    test_details_json = json.loads(TEST_RESULT_PATH.read_text())
    test_details_parsed = []
    for subtask in test_details_json:
        subtask_details = TestResult(**subtask)
        test_details_parsed.append(subtask_details)

    return output_log_path.read_text(), test_details_parsed

def cmd_submit(_):
    print_ok('[+] Submitting instance..', flush=True)

    test_output, test_results = _run_tests()
    any_test_failed =  any([not t.success for t in test_results])

    if any_test_failed:
        print_warn('[!] Failing tests may indicate that your solution is erroneous or not complete yet.')
        print_warn('[!] Are you sure you want to submit? [y/n] ', end='')
        if not user_answered_yes():
            exit(0)
    else:
        print_ok('[+] Are you sure you want to submit? [y/n] ', end='')
        if not user_answered_yes():
            exit(0)

    if len(test_output) > MAX_TEST_OUTPUT_LENGTH:
        print_err(f'[!] Test output exceeded maximum length of {MAX_TEST_OUTPUT_LENGTH} characters.')
        print_err(f'[!] You need to trim the output of your solution script(s) to submit!')
        exit(0)

    print_ok("[+] Submitting now...", flush=True)

    req = {
        'output': test_output,
        'test_results': [asdict(e) for e in test_results]
    }

    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/submit', json=req)
    _, ret = handle_response(res)
    print_ok(ret)

def cmd_check(_):
    """
    Run a script that is specific to the current task and print its output?
    """
    _run_tests()

def cmd_id(_):
    print_ok('[+] If you need support, please provide this ID alongside your request.')
    print_ok(f'[+] Instance ID: {INSTANCE_ID}')

def cmd_info(_):
    req = {
    }
    req = finalize_request(req)
    res = requests.post('http://sshserver:8000/api/instance/info', json=req)
    _, info = handle_response(res)
    print(info)


def main():
    parser = argparse.ArgumentParser(prog="task")
    subparsers = parser.add_subparsers(dest='command')
    subparsers.required = True

    if not IS_SUBMISSION:
        # Copy the 'snapshotted' user environment stored at /tmp/.user_environ.
        # The `/tmp/.user_environ` file is created by `task-wrapper.c`
        # just before this script is executed.
        p = Path('/home/user/.user_environ')
        if p.exists():
            # Grant permission in case the user messed with `.user_environ`.
            p.chmod(0o777)
            p.unlink()
        shutil.copy('/tmp/.user_environ', '/home/user/.user_environ')

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

    info_parser = subparsers.add_parser('info',
        help='Get various details of this instance.'
        )
    info_parser.set_defaults(func=cmd_info)

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
