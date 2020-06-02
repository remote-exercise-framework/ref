#!/bin/bash

#Dump environ thus we can restore it after dropping privileges.
printenv > /tmp/.user_environ

#Execute the actual task script.
sudo /usr/local/bin/_task $@
