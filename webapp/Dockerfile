FROM python:3.7

ARG DOCKER_GROUP_ID

# Install dependencies
WORKDIR /tmp/
RUN apt-get update && apt-get install -y docker docker.io git python3 sudo dnsutils wget netcat

RUN wget https://raw.githubusercontent.com/eficode/wait-for/master/wait-for -O /usr/bin/wait-for \
    && chmod 555 /usr/bin/wait-for

COPY requirements.txt /tmp/
RUN pip install -r requirements.txt && rm requirements.txt

RUN groupmod -g $DOCKER_GROUP_ID docker
RUN useradd -G docker,sudo -ms /bin/bash user
RUN mkdir -p /app && chown user /app

RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

WORKDIR /app/

COPY . .
RUN pip install -e .


RUN chown -R user /app
#USER user

# Run
#EXPOSE 8000
CMD ["./run-server.sh"]
