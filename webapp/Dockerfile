FROM python:3.13.1-bookworm

ENV PYTHONIOENCODING=UTF-8

ARG DOCKER_GROUP_ID

# Install dependencies
WORKDIR /tmp/
RUN apt-get update && apt-get install -y docker docker.io git python3 sudo dnsutils wget curl netcat-traditional rsync attr inotify-tools

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

RUN wget -4 https://raw.githubusercontent.com/eficode/wait-for/master/wait-for -O /usr/bin/wait-for \
    && chmod 555 /usr/bin/wait-for

COPY pyproject.toml /tmp/
RUN uv pip install --system --break-system-packages . && rm pyproject.toml

# Install coverage for code coverage collection during e2e tests
RUN uv pip install --system --break-system-packages coverage

# Copy sitecustomize.py for automatic coverage collection
COPY coverage/sitecustomize.py /usr/local/lib/python3.13/site-packages/sitecustomize.py
RUN chmod 644 /usr/local/lib/python3.13/site-packages/sitecustomize.py

# Create coverage data directory
RUN mkdir -p /coverage-data && chmod 777 /coverage-data

# This may fail if the group already has the specified id.
RUN  groupmod -g $DOCKER_GROUP_ID docker || true
RUN useradd -G docker,sudo -ms /bin/bash user
RUN mkdir -p /app && chown user /app

RUN echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

WORKDIR /app/

COPY . .
#RUN pip install -e .


RUN chown -R user /app
#USER user

# Run
#EXPOSE 8000
CMD ["./run-server.sh"]
