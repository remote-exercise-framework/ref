#!/bin/bash

#
# This script builds a live kernel patch that causes the
# disable ASLR personality to not be dropped in case a
# SETUID binary is executed.
#

if [[ ! -f /etc/lsb-release ]]; then
    echo "ASLR patching is currently only available for Ubuntu"
    exit 1
fi

source /etc/lsb-release

if [[ "$DISTRIB_ID" != "Ubuntu" ]]; then
    echo "Distribution $DISTRIB_ID is not supported"
    exit 1
fi

if [[ "$DISTRIB_RELEASE" != "18.04" ]]; then
    echo "Ubuntu version $DISTRIB_RELEASE may not work..."
fi

path="patches/ubuntu/$(uname -r)/livepatch-keep-aslr-personality-on-setuid.ko"
if [[ -f "$path" ]]; then
    echo "Found compatible module at $path."
    exit 0
fi


sudo apt-get install linux-image-$(uname -r)-dbgsym || exit 1
sudo apt-get build-dep linux linux-image-$(uname -r)

kpatch-build -j7 -t vmlinux keep-aslr-personality-on-setuid.patch
if [[ $? != 0 ]]; then
    echo "Oops, something went wrong."
    echo "Please make sure you have build kpatch from git, since Ubuntus"
    echo "repository package is outdated."
    echo "Please install all dependencies listed in the Ubuntu section"
    echo "on https://github.com/dynup/kpatch".
    exit 1
fi
