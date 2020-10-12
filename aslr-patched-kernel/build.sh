#!/bin/bash

set -e

sudo apt install -y build-essential linux-source bc kmod cpio flex cpio libncurses5-dev

cp /usr/src/linux-source-4.19.tar.xz ./linux-source-4.19.tar.xz
tar xavf ./linux-source-4.19.tar.xz

cp /boot/config-4.19.0-10-rt-amd64 linux-source-4.19/.config

cd linux-source-4.19
sed -ri '/CONFIG_SYSTEM_TRUSTED_KEYS/s/=.+/=""/g' .config
patch -p1 < ../keep-aslr-personality-on-setuid.patch

make clean
make olddefconfig


make -j`nproc` bindeb-pkg


#dpkg -i linux-image-4.19.132_4.19.132-1_amd64.deb linux-headers-4.19.132_4.19.132-1_amd64.deb linux-libc-dev_4.19.132-1_amd64.deb
