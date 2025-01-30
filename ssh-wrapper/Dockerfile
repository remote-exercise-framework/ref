FROM python:3.13.1-bookworm
SHELL ["/bin/bash", "-c"]

RUN apt update && apt install -y sudo gcc git autoconf zlib1g-dev \
    libssl-dev build-essential valgrind tinyproxy wget curl netcat-traditional

# Install cargo
RUN curl https://sh.rustup.rs -sSf | bash -s -- -y
RUN echo 'source $HOME/.cargo/env' >> $HOME/.bashrc

RUN mkdir -p /var/run/sshd

RUN wget -4 https://raw.githubusercontent.com/eficode/wait-for/master/wait-for -O /usr/bin/wait-for \
    && chmod 555 /usr/bin/wait-for

RUN useradd -m -d /home/sshd -s /bin/bash sshd

# This is the user that is used for login for all connections
# that could successfully be authenticated. 
#It looks like the sshserver needs a password to allow
#login through SSH. So, we set a random one.
RUN useradd -m -d /home/sshserver -s /bin/bash sshserver \
    && echo "sshserver:$(openssl rand -base64 32)" | chpasswd

WORKDIR /tmp
COPY requirements.txt /tmp/
RUN pip install -r requirements.txt && rm requirements.txt

# Install the interfacing library that is used by sshd to communicate
# via rest with the web server.
COPY "ref-interface" ./ref-interface
RUN cd "ref-interface" \
    && bash -c "source $HOME/.bashrc && cargo build" \
    && cp "$(find $PWD/target -name 'libref_interface.so' | head -n 1)" /usr/lib/libref_interface.so \
    && cp "$(find $PWD/target -name 'libref_interface.a' | head -n 1)" /usr/lib/libref_interface.a \
    && cp ref_interface.h /usr/include/

WORKDIR /home/sshserver

COPY openssh-portable openssh-portable
RUN ldconfig && cd openssh-portable \
    && autoreconf && ./configure --help  && ./configure --with-libs="/usr/lib/libref_interface.so" || cat config.log \
    && make -j && make install

COPY sshd_config /etc/ssh/sshd_config
COPY ssh_config /etc/ssh/ssh_config

#This script is run for each connection made to the SSH server
COPY ssh-wrapper.py /usr/bin/ssh-wrapper.py

#This script is called before authorized_keys is consulted.
COPY ssh-authorized-keys.py /usr/bin/ssh-authorized-keys.py
RUN chmod 755 /usr/bin/ssh-authorized-keys.py

#Startscript
COPY run-service.sh /home/sshserver/
COPY tinyproxy.conf /home/sshserver/

RUN mkdir .ssh

#Key used for authenticating at the spawned docker instances.
COPY container-keys/* .ssh/
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
