FROM ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt update

RUN apt install -y \
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
    netcat-traditional \
    hexcurse \
    clang \
    socat \
    man-db \
    rsync \
    sysbench \
    htop \
    gdb \
    nano \
    nasm \
    screen tmux \
    vim \
    neovim \
    strace \
    attr \
    pkg-config \
    libcairo2-dev \
    gnuplot \
    curl

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install Python dependencies using uv
COPY pyproject.toml /tmp/pyproject.toml
RUN cd /tmp && uv pip install --system --break-system-packages . && rm /tmp/pyproject.toml

RUN wget -4 https://raw.githubusercontent.com/eficode/wait-for/master/wait-for -O /usr/bin/wait-for \
    && chmod 555 /usr/bin/wait-for

COPY wait-for-host /usr/bin/wait-for-host
RUN  chmod 555 /usr/bin/wait-for-host

# 2. Setup related stuff
RUN mkdir -p /run/sshd

# Create user and use its home as workdir
RUN groupadd -g 9999 user && useradd -g 9999 -u 9999 -d /home/user -m -s /bin/bash user

WORKDIR /root

RUN mkdir -p .ssh && chmod 700 .ssh

WORKDIR /home/user

# Log timestamps for each executed command in the bashrc
RUN echo 'export HISTTIMEFORMAT="%F %T "' >> .bashrc

# Flush commands immediately to the history
RUN echo 'export PROMPT_COMMAND="history -a"' >> .bashrc

COPY <<EOF /home/user/.nanorc
set linenumbers
set tabsize 4
set tabstospaces
EOF

RUN mkdir .ssh && chmod 700 .ssh

# Directory for master keys volume-mounted from the host at runtime.
# sshd_config references /etc/ssh/master_keys/%u for key lookup.
RUN mkdir -p /etc/ssh/master_keys

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
RUN wget -4 -O /home/user/.gdbinit-gef.py -q https://gef.blah.cat/py \
    && echo source /home/user/.gdbinit-gef.py >> /home/user/.gdbinit \
    && chown user:user /home/user/.gdbinit

# Copy mypy and pylint configs
COPY pylintrc /etc/pylintrc
COPY mypyrc /etc/mypyrc

# Unset variables only set by GDB
RUN echo "unset environment LINES" >> .gdbinit && \
    echo "unset environment COLUMNS" >> .gdbinit

# Import and install ref-utils in editable mode so a runtime bind-mount of
# the host source at /opt/ref-utils live-updates the package without a rebuild.
COPY ref-utils /opt/ref-utils
RUN cd /opt/ref-utils && \
    uv pip install --system --break-system-packages -e .

# Install coverage for code coverage collection during e2e tests
RUN uv pip install --system --break-system-packages coverage

# Copy sitecustomize.py for automatic coverage collection
# Ubuntu 24.04 uses Python 3.12
COPY coverage/sitecustomize.py /usr/lib/python3/dist-packages/sitecustomize.py
RUN chmod 644 /usr/lib/python3/dist-packages/sitecustomize.py

# Create coverage data directory (student containers write to /shared)
RUN mkdir -p /shared && chmod 777 /shared

RUN rm -rf /tmp/*
