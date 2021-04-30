FROM nbars/ubuntu-unminimized-base-docker:20.04 as ref_utils_builder
ARG DEBIAN_FRONTEND=noninteractive

RUN apt update && \
    apt install -y python3 python3-pip python3-setuptools && \
    python3 -m pip install -U pip setuptools wheel

COPY ref-utils /home/ref-utils
RUN cd /home/ref-utils && \
    python3 setup.py bdist_wheel



FROM nbars/ubuntu-unminimized-base-docker:20.04

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
    software-properties-common \
    sudo \
    netcat \
    hexcurse \
    clang \
    socat \
    man-db \
    rsync \
    sysbench

# Restore stripped stuff like man pages
RUN yes | unminimize

RUN wget https://raw.githubusercontent.com/eficode/wait-for/master/wait-for -O /usr/bin/wait-for \
    && chmod 555 /usr/bin/wait-for

COPY wait-for-host /usr/bin/wait-for-host
RUN  chmod 555 /usr/bin/wait-for-host

RUN cd /tmp && git clone https://github.com/rofl0r/microsocks.git \
    && cd microsocks \
    && make install \
    && cd .. && rm -rf /tmp/microsocks

# 2. Setup related stuff
RUN mkdir -p /run/sshd

# Group and user that is used to run the socks proxy related stuff.
RUN groupadd -g 9911 socks && useradd -g 9911 -u 9911 -s /bin/false socks

# Create user and use its home as workdir
RUN groupadd -g 9999 user && useradd -g 9999 -u 9999 -d /home/user -m -s /bin/bash user

WORKDIR /root

RUN mkdir .ssh
COPY container-key/root-container.pub .ssh/authorized_keys
RUN chown root:root .ssh/authorized_keys \
    && chmod 644 .ssh/authorized_keys

WORKDIR /home/user

# Log timestamps for each executed command in the bashrc
RUN echo 'export HISTTIMEFORMAT="%F %T "' >> .bashrc

# Flush commands immediately to the history
RUN echo 'export PROMPT_COMMAND="history -a"' >> .bashrc

# Deploy the default ssh-key that is used for authentication by the ssh entry server as user "user".
RUN mkdir .ssh
COPY container-key/user-container.pub .ssh/authorized_keys
RUN chown root:root .ssh/authorized_keys \
    && chmod 644 .ssh/authorized_keys

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

# Allow the user to run _task using sudo. We can not use setuid, since
# this is a python script.
RUN echo "user ALL=(ALL) NOPASSWD: /usr/local/bin/_task" >> /etc/sudoers

# Install wrapper for the _task script that dumps the users environment
# and calls sudo /usr/local/bin/_task.
COPY task-wrapper.c /tmp/task-wrapper.c
RUN gcc -O3 -Wall -Werror -Wl,-z,rel -D_FORTIFY_SOURCE=2 -pie -fPIE \
    -fstack-protector-strong /tmp/task-wrapper.c -o /usr/local/bin/task
RUN chmod 555 /usr/local/bin/task

# -D: Deamon
# -e: Log to stdout instead of syslog
CMD ["/usr/sbin/sshd", "-D", "-e"]

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
    vim \
    clang

RUN python3 -m pip install --upgrade pwntools

# Import and install ref-utils
COPY --from=ref_utils_builder /home/ref-utils/dist/ref_utils-*-py3-none-any.whl /tmp
RUN python3 -m pip install -U pip setuptools wheel && \
    python3 -m pip install -U /tmp/ref_utils-*-py3-none-any.whl && \
    rm -f /tmp/ref_utils-*-py3-none-any.whl
