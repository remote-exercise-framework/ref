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

sys.path.append('/usr/local/lib/python3.7/site-packages')
try:
    import requests
    from itsdangerous import Serializer
except:
    raise

#Secret used to sign messages send from the SSH server to the webserver
with open('/etc/request_key', 'rb') as f:
    SECRET_KEY = f.read()

CONTAINER_STARTUP_TIMEOUT = 10

def get_header():
    req = {
    }

    s = Serializer(SECRET_KEY)
    req = s.dumps(req)
    res = requests.post('http://web:8000/api/header', json=req)

    try:
        json = res.json()
        return 200, json
    except ValueError:
        return 400, 'Missing JSON body'
    except Exception:
        return 400, 'Internal Error'

def get_user_info(pubkey):
    req = {
        'pubkey': pubkey
    }

    s = Serializer(SECRET_KEY)
    req = s.dumps(req)
    res = requests.post('http://web:8000/api/getuserinfo', json=req)

    try:
        json = res.json()
        return 200, json
    except ValueError:
        return 400, 'Missing JSON body'
    except Exception:
        return 400, 'Internal Error'

def get_container(username, pubkey):
    req = {
        'username': username,
        'pubkey': pubkey
    }

    s = Serializer(SECRET_KEY)
    req = s.dumps(req)
    res = requests.post('http://web:8000/api/provision', json=req)

    try:
        json = res.json()
        return res.status_code, json
    except ValueError:
        return 400, 'Missing JSON body'
    except Exception:
        return 400, 'Internal Error'

def main():
    #The username that was provided by the client as login name.
    real_user = os.environ['REAL_USER']

    #The username that is used to execute this script
    # user = os.environ['USER']

    #Path to the user auth file that contains the pub-key that was used for authentication.
    user_auth_path = os.environ['SSH_USER_AUTH']

    with open(user_auth_path, 'r') as f:
        pubkey = f.read()
        pubkey = " ".join(pubkey.split(' ')[1:]).rstrip()

    status_code, resp = get_user_info(pubkey)
    if status_code != 200:
        if isinstance(resp, str):
            print(resp)
        else:
            print(resp['error'])
        exit(1)

    real_name = resp['name']
    status_code, resp = get_header()
    if status_code != 200:
        print(f'Error: {resp}')
        exit(1)
    print(resp)


    print(f'Hello {real_name}!\nTrying to connect to task "{real_user}"...')
    status_code, resp = get_container(real_user, pubkey)

    if status_code != 200:
        if isinstance(resp, str):
            print(resp)
        else:
            print(resp['error'])
        exit(1)

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
        print('If the problems persist, please contact your system administrator.', flush=True)
        exit(1)

    os.execvp('/usr/bin/ssh', cmd)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print('Bye bye\n', flush=True)
    except Exception as e:
        print(traceback.format_exc(), flush=True)
