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
    nasm \
    gdb=8.1-0ubuntu3 \
    libc6 libstdc++6 python-minimal ca-certificates tar \
    python2.7 python-pip python-dev git libssl-dev libffi-dev build-essential

RUN pip install --upgrade pwntools

#Current version of gdb is broken. Prevent update until a fix was released.
#https://stackoverflow.com/questions/58225562/how-to-fix-hang-in-gdb-in-ld-linux-so-2-when-running-a-32-bit-executable-on-a-64
RUN apt-mark hold gdb

RUN apt install -y \
    net-tools \
    iproute2 \
    iputils-ping

RUN pip3 install ipython

RUN apt install -y screen tmux

RUN groupadd -g 9999 user && useradd -g 9999 -u 9999 -d /home/user -m -s /bin/bash user
RUN groupadd -g 7799 admin && useradd -g 7799 -u 7799 -s /bin/false admin

RUN groupadd -g 8001 admin0 && useradd -g 8001 -u 8001 -s /bin/false admin0
RUN groupadd -g 8002 admin1 && useradd -g 8002 -u 8002 -s /bin/false admin1
RUN groupadd -g 8003 admin2 && useradd -g 8003 -u 8003 -s /bin/false admin2

RUN echo "user:user" | chpasswd

RUN mkdir -p /run/sshd

WORKDIR /home/user
RUN mkdir .ssh
COPY container-key/container-key.pub .ssh/authorized_keys
RUN chown root:root .ssh/authorized_keys \
    && chmod 444 .ssh/authorized_keys

#Install gef
RUN wget -O /home/user/.gdbinit-gef.py -q https://github.com/hugsy/gef/raw/master/gef.py \
    && echo source /home/user/.gdbinit-gef.py >> /home/user/.gdbinit \
    && chown user:user /home/user/.gdbinit

COPY sshd_config /etc/ssh/sshd_config

#Disable Ubuntu welcome message
RUN chmod -x /etc/update-motd.d/* && rm /etc/legal

#Replace /bin/sh with a shell that does not drop privileges
#in case euid != uid.
COPY my-shell.c /tmp/my-shell.c
RUN gcc /tmp/my-shell.c -o /bin/sh && rm /tmp/my-shell.c

CMD ["/usr/sbin/sshd", "-D"]

# Install and provide command to source reset-env script resetting the environment
COPY reset-env /bin/
RUN echo 'alias reset-env="source /bin/reset-env"' >> /etc/profile
# Unset variables only set by GDB
RUN echo "unset environment LINES" >> .gdbinit
RUN echo "unset environment COLUMNS" >> .gdbinit
RUN echo "unset environment _" >> .gdbinit
