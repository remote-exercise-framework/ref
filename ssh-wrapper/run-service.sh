#!/bin/bash
set -e

echo "[+] Starting reverse proxy"
tinyproxy -d -c /home/sshserver/tinyproxy.conf &

echo "[+] Generating SSH Server keys"
chown -R root:root /ssh-server-keys
for type in ecdsa ed25519; do
    dst="/ssh-server-keys/ssh_host_${type}_key"
    if [[ ! -f "$dst" ]]; then
        echo "[+] Generating key: $dst"
        ssh-keygen -t ${type} -N "" -f "$dst"
    fi
done

echo "[+] Starting SSH Server"
/usr/local/sbin/sshd -e -D -f /etc/ssh/sshd_config
