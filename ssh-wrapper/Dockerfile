FROM python:3.7
MAINTAINER Nils Bars <nils.bars@rub.de>

RUN apt update && apt install -y sudo gcc git autoconf zlib1g-dev libssl-dev build-essential valgrind netcat tinyproxy
RUN mkdir -p /var/run/sshd

RUN useradd -m -d /home/sshd -s /bin/bash sshd

#It looks like the sshserver needs a password to allow
#login through SSH. So, we set a random one.
RUN useradd -m -d /home/sshserver -s /bin/bash sshserver \
    && echo "sshserver:$(openssl rand -base64 32)" | chpasswd

WORKDIR /tmp
COPY requirements.txt /tmp/
RUN pip install -r requirements.txt && rm requirements.txt

WORKDIR /home/sshserver

COPY openssh-portable openssh-portable
RUN cd openssh-portable \
    && autoconf && autoheader && ./configure \
    && make && make install

COPY sshd_config /etc/ssh/sshd_config
COPY ssh_config /etc/ssh/ssh_config

#This script is run for each connection made to the SSH server
COPY ssh-wrapper.py /usr/bin/ssh-wrapper.py

#This script is called before authorized_keys is consulted.
COPY ssh-authorized-keys.py /usr/bin/ssh-authorized-keys.py
RUN chmod 755 /usr/bin/ssh-authorized-keys.py

#Server SSH keys + permissions
COPY server-key/ssh_host_rsa_key /etc/ssh/ssh_host_rsa_key
COPY server-key/ssh_host_rsa_key.pub /etc/ssh/ssh_host_rsa_key.pub
RUN chmod 600 /etc/ssh/ssh_host_rsa_key
RUN chmod 600 /etc/ssh/ssh_host_rsa_key.pub

#Startscript
COPY run-service.sh /home/sshserver/
COPY tinyproxy.conf /home/sshserver/

RUN mkdir .ssh

#Key used for authenticating at the spawned docker instances.
COPY container-key/* .ssh/
RUN chown -R sshserver:users .ssh
RUN chmod 600 .ssh/*

#Save siging key as file. This key is used to
#sign requests from the ssh server to the web server.
ARG SSH_TO_WEB_KEY
RUN echo -n "$SSH_TO_WEB_KEY" > /etc/request_key \
    && chown sshserver:users /etc/request_key \
    && chmod 400 /etc/request_key

# Default command
CMD ["/home/sshserver/run-service.sh"]
