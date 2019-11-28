#!/bin/bash

path="patches/ubuntu/$(uname -r)/livepatch-keep-aslr-personality-on-setuid.ko"
if [[ ! -f "$path" ]]; then
    echo "Failed to find path compatible with the kernel currently running"
    exit 1
fi

sudo kpatch load "$path"