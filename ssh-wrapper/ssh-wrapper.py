#!/usr/bin/env python3.7

"""
This script is executed each time a SSH connection is successfully established
to the SSH server. The main task of this script is to determine the IP address
of the task container of the connected user. 
"""

import os
import socket
import sys
import time
import traceback
import typing

sys.path.append('/usr/local/lib/python3.7/site-packages')
try:
    import requests
    from itsdangerous import Serializer
    from colorama import Fore, Style
except:
    raise

def print_ok(*args, **kwargs):
    print(Fore.GREEN, *args, Style.RESET_ALL, **kwargs, sep='')

def print_warn(*args, **kwargs):
    print(Fore.YELLOW, *args, Style.RESET_ALL, **kwargs, sep='')

def print_err(*args, **kwargs):
    print(Fore.RED, *args, Style.RESET_ALL, **kwargs, sep='')

#Secret used to sign messages send from the SSH server to the webserver
with open('/etc/request_key', 'rb') as f:
    SECRET_KEY = f.read()

CONTAINER_STARTUP_TIMEOUT = 10

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
            print_err(f'[!] ', 'Unknown error! Please contact staff')
        exit(1)

def do_post(url, json, expected_status=(200, )) -> typing.Tuple[int, typing.Dict]:
    """
    Do a POST request on `url` and pass `json` as request data.
    If the target answer with a status code not in expected_status,
    the program is terminated and an error message is displayed
    to the user. If the status code is found in expected_status,
    and the response contains a JSON body, a tuple status_code, json_body
    is returned.
    """
    try:
        resp = requests.post(url, json=json)
    except Exception as e:
        print_err(f'[!] Unknown error. Please contact the staff!\n{e}.')
        exit(1)

    return handle_response(resp, expected_status=expected_status)

def sign(m):
    s = Serializer(SECRET_KEY)
    return s.dumps(m)

def get_header():
    req = {}
    req = sign(req)

    _, ret = do_post('http://web:8000/api/header', json=req)
    return ret
    

def get_user_info(pubkey):
    req = {
        'pubkey': pubkey
    }
    req = sign(req)

    _, ret = do_post('http://web:8000/api/getuserinfo', json=req)
    return ret

def get_container(username, pubkey):
    req = {
        'username': username,
        'pubkey': pubkey
    }
    req = sign(req)

    _, ret = do_post('http://web:8000/api/provision', json=req)
    return ret

def main():
    #The username that was provided by the client as login name (ssh [name]@192...).
    real_user = os.environ['REAL_USER']

    #Path to a file that contains the pub-key that was used for authentication (created by sshd)
    user_auth_path = os.environ['SSH_USER_AUTH']

    #Get the SSH-Key in OpenSSH format
    with open(user_auth_path, 'r') as f:
        pubkey = f.read()
        pubkey = " ".join(pubkey.split(' ')[1:]).rstrip()

    #Get infos about the user that owns the given key.
    resp = get_user_info(pubkey)

    #Real name of the user/student
    real_name = resp['name']

    #Welcome header (e.g., OSSec as ASCII-Art)
    resp = get_header()
    print(resp)

    #Greet the connected user
    print(f'Hello {real_name}!\nTrying to connect to task "{real_user}"...')


    #Get the details needed to connect to the users container. 
    resp = get_container(real_user, pubkey)

    #Welcome message specific to this container.
    #E.g., submission status, time until deadline...
    msg = resp['welcome_message']
    print(msg)

    ip = resp['ip']
    cmd = ['/usr/bin/ssh', '-t', '-o', ' StrictHostKeyChecking=no', '-i', '/home/sshserver/.ssh/container-key', '-p', '13370', '-l', 'user', ip]

    #Cmd provided by the client
    ssh_cmd = os.environ.get("SSH_ORIGINAL_COMMAND")
    #Cmd used if nothing was provided
    default_cmd = resp['cmd']

    if ssh_cmd:
        cmd += [ssh_cmd]
    elif default_cmd:
        cmd += default_cmd

    #Give the container some time to start
    start_ts = time.time()
    result = None
    while (time.time() - start_ts) < CONTAINER_STARTUP_TIMEOUT:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #returns errno
        result = sock.connect_ex((str(ip), 13370))
        sock.close()
        if result == 0:
            break

    if result != 0:
        print('Failed to connect. Please try again.', flush=True)
        print('If the problem persist, please contact your system administrator.', flush=True)
        exit(1)

    os.execvp('/usr/bin/ssh', cmd)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Bye bye\n', flush=True)
    except Exception as e:
        print(traceback.format_exc(), flush=True)
