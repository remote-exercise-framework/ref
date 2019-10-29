#!/usr/bin/env python3.7

#ExposeAuthInfo
#SSH_USER_AUTH
#ForceCommand

#/usr/bin/ssh -t -o StrictHostKeyChecking=no $USER@${1:-default}.fqdn $SSH_ORIGINAL_COMMAND

#ForceCommand
import os
import time
import socket
import traceback
import sys
sys.path.append('/usr/local/lib/python3.7/site-packages')
import requests


CONTAINER_STARTUP_TIMEOUT = 10

def get_user_info(pubkey):
    req = {
        'pubkey': pubkey
    }

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

    res = requests.post('http://web:8000/api/provision', json=req)

    try:
        json = res.json()
        return res.status_code, json
    except ValueError:
        return 400, 'Missing JSON body'
    except Exception:
        return 400, 'Internal Error'



header = """
  ____  ____  ____                 _ __      
 / __ \/ __/ / __/__ ______ ______(_) /___ __
/ /_/ /\ \  _\ \/ -_) __/ // / __/ / __/ // /
\____/___/ /___/\__/\__/\_,_/_/ /_/\__/\_, / 
                                      /___/  
"""

header_title = """
Time wasted debugging: 13h 43m 11s
"""

def main():
    #TODO: Drop privileges 

    #The username that was provided by the client as login name.
    real_user = os.environ['REAL_USER']

    #The username that is used to execute this script
    # user = os.environ['USER']

    #Path to the user auth file that contains the pub-key that was used for authentication.
    user_auth_path = os.environ['SSH_USER_AUTH']

    with open(user_auth_path, 'r') as f:
        pubkey = f.read()
        pubkey = " ".join(pubkey.split(' ')[1:]).rstrip()

    # print(f"User {real_user} logged in.")
    # print(f"Pubkey={pubkey}")

    status_code, resp = get_user_info(pubkey)
    if status_code != 200:
        if isinstance(repr, str):
            print(resp)
        else:
            print(resp['error'])
        exit(1)

    real_name = resp['name']
    print(header, end='')
    #print(header_title)

    print(f'Hello {real_name}!\n Trying to connect to task "{real_user}"...')
    status_code, resp = get_container(real_user, pubkey)

    if status_code != 200:
        if isinstance(resp, str):
            print(resp)
        else:
            print(resp['error'])
        exit(1)

    #print('Requesting IP', flush=True)
    ip = resp['ip']
    #print(f'Got IP {ip}', flush=True)

    #print(f'SSH_ORIGINAL_COMMAND={os.environ.get("SSH_ORIGINAL_COMMAND")}', flush=True)
    ssh_cmd = os.environ.get("SSH_ORIGINAL_COMMAND")

    cmd = ['/usr/bin/ssh', '-t', '-o', ' StrictHostKeyChecking=no', '-i', '/home/sshserver/.ssh/container-key', '-p', '13370', '-l', 'user', ip]
    #FIXME: Check whether bind executable is used
    if ssh_cmd:
        cmd += [ssh_cmd]


    #Give the container some time to start
    start_ts = time.time()
    result = None
    while (time.time() - start_ts) < CONTAINER_STARTUP_TIMEOUT:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
