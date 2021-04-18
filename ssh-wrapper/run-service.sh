#!/bin/bash
set -e

echo "[+] Starting reverse proxy"
tinyproxy -d -c /home/sshserver/tinyproxy.conf &

echo "[+] Starting SSH Server"
/usr/local/sbin/sshd -e -D -f /etc/ssh/sshd_config
