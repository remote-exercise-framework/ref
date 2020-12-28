FROM ubuntu:18.04 as ref_utils_builder
ARG DEBIAN_FRONTEND=noninteractive

RUN apt update && \
    apt install -y python3 python3-pip python3-setuptools && \
    python3 -m pip install -U pip setuptools wheel

COPY ref-utils /home/ref-utils
RUN cd /home/ref-utils && \
    python3 setup.py bdist_wheel



FROM ubuntu:18.04

ARG DEBIAN_FRONTEND=noninteractive

# 1. Install packages necessary for setup
RUN apt update && apt install -y \
    build-essential \
    ca-certificates \
    gcc gcc-multilib g++-multilib \
    git \
    iproute2 iputils-ping net-tools \
    libssl-dev libffi-dev \
    make \
    openssh-server \
    python3 python3-pip \
    python python-dev python-pip \
    software-properties-common \
    sudo \
    netcat

RUN wget https://raw.githubusercontent.com/eficode/wait-for/master/wait-for -O /usr/bin/wait-for \
    && chmod 555 /usr/bin/wait-for

COPY wait-for-host /usr/bin/wait-for-host
RUN  chmod 555 /usr/bin/wait-for-host

# 2. Setup related stuff
RUN mkdir -p /run/sshd

# Create user and use its home as workdir
RUN groupadd -g 9999 user && useradd -g 9999 -u 9999 -d /home/user -m -s /bin/bash user
WORKDIR /home/user

# Log timestamps for each executed command in the bashrc
RUN echo 'export HISTTIMEFORMAT="%F %T "' >> .bashrc

# Flush commands immediately to the history
RUN echo 'export PROMPT_COMMAND="history -a"' >> .bashrc

# Deploy the default ssh-key that is used for authentication by the ssh entry server.
RUN mkdir .ssh
COPY container-key/container-key.pub .ssh/authorized_keys
RUN chown root:root .ssh/authorized_keys \
    && chmod 444 .ssh/authorized_keys

COPY sshd_config /etc/ssh/sshd_config

# Replace /bin/sh with a shell that does not drop privileges
# in case euid != uid.
COPY my-shell.c /tmp/my-shell.c
RUN gcc /tmp/my-shell.c -o /bin/sh && rm /tmp/my-shell.c

#Disable Ubuntu welcome message
RUN chmod -x /etc/update-motd.d/* && rm /etc/legal

# Install submit/reset script
COPY task.py /usr/local/bin/_task
RUN chown root:root /usr/local/bin/_task \
    && chmod 500 /usr/local/bin/_task

#Allow the user run _task using sudo. We can not use setuid since
#this is a python script.
RUN echo "user ALL=(ALL) NOPASSWD: /usr/local/bin/_task" >> /etc/sudoers

# Install wrapper for the _task script.
COPY task-wrapper.c /tmp/task-wrapper.c
RUN gcc /tmp/task-wrapper.c -o /usr/local/bin/task
RUN chmod 555 /usr/local/bin/task

CMD ["/usr/sbin/sshd", "-D"]

# 3. Convenience stuff
# Create users: user, admin
RUN groupadd -g 7799 admin  && useradd -g 7799 -u 7799 -s /bin/false admin  && \
    groupadd -g 8001 admin0 && useradd -g 8001 -u 8001 -s /bin/false admin0 && \
    groupadd -g 8002 admin1 && useradd -g 8002 -u 8002 -s /bin/false admin1 && \
    groupadd -g 8003 admin2 && useradd -g 8003 -u 8003 -s /bin/false admin2

RUN echo "user:user" | chpasswd

# Install gef
RUN wget -O /home/user/.gdbinit-gef.py -q https://github.com/hugsy/gef/raw/master/gef.py \
    && echo source /home/user/.gdbinit-gef.py >> /home/user/.gdbinit \
    && chown user:user /home/user/.gdbinit

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy mypy and pylint configs
COPY pylintrc /etc/pylintrc
COPY mypyrc /etc/mypyrc

# Unset variables only set by GDB
RUN echo "unset environment LINES" >> .gdbinit && \
    echo "unset environment COLUMNS" >> .gdbinit

# Install convenience packages the users might want to use
RUN apt update && apt install -y \
    gdb \
    nano \
    nasm \
    screen tmux \
    vim

RUN pip install --upgrade pwntools

# Import and install ref-utils
COPY --from=ref_utils_builder /home/ref-utils/dist/ref_utils-*-py3-none-any.whl /tmp
RUN python3 -m pip install -U pip setuptools wheel && \
    python3 -m pip install -U /tmp/ref_utils-*-py3-none-any.whl && \
    rm -f /tmp/ref_utils-*-py3-none-any.whl
