FROM python:3.7
MAINTAINER Nils Bars <nils.bars@rub.de>

RUN apt update && apt install -y sudo gcc git autoconf zlib1g-dev libssl-dev build-essential valgrind netcat
RUN mkdir -p /var/run/sshd

RUN useradd -m -d /home/sshd -s /bin/bash sshd \
    && echo "sshd:sshd" | chpasswd

RUN useradd -m -d /home/sshserver -s /bin/bash sshserver \
    && echo "sshserver:sshserver" | chpasswd

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

COPY ssh-wrapper.py /usr/bin/ssh-wrapper.py
COPY ssh-authorized-keys.py /usr/bin/ssh-authorized-keys.py
RUN chmod 755 /usr/bin/ssh-authorized-keys.py
COPY server-key/ssh_host_rsa_key /etc/ssh/ssh_host_rsa_key
COPY server-key/ssh_host_rsa_key.pub /etc/ssh/ssh_host_rsa_key.pub

COPY run-service.sh /home/sshserver/
RUN mkdir .ssh
COPY container-key/* .ssh/
RUN chown -R sshserver:users .ssh


# Default command
CMD ["/home/sshserver/run-service.sh"]