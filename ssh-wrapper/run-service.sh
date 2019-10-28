#!/bin/bash
set -e

echo "[+] Starting SSH Server"
/usr/local/sbin/sshd -D -f /etc/ssh/sshd_config
