FROM ubuntu:18.04

RUN apt update
RUN apt upgrade -y
RUN apt install -y \
    make \
    gcc \
    python \
    git gcc-multilib g++-multilib \
    software-properties-common \
    python3 \
    python3-pip \
    openssh-server \
    nano \
    vim \
    nasm

RUN apt install -y \
    net-tools \
    iproute2 \
    iputils-ping

RUN pip3 install ipython

RUN groupadd -g 9999 user && useradd -g 9999 -u 9999 -d /home/user -m -s /bin/bash user
RUN echo "user:user" | chpasswd

RUN mkdir -p /run/sshd

WORKDIR /home/user
RUN mkdir .ssh
COPY container-key/container-key.pub .ssh/authorized_keys
RUN chown root:root .ssh/authorized_keys \
    && chmod 444 .ssh/authorized_keys

COPY sshd_config /etc/ssh/sshd_config

#Disable Ubuntu welcome message
RUN chmod -x /etc/update-motd.d/* && rm /etc/legal

CMD ["/usr/sbin/sshd", "-D"]

