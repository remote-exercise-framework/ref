#!/bin/bash

set -eu

text_red=$(tput setaf 1)    # Red
text_green=$(tput setaf 2)  # Green
text_yellow=$(tput setaf 3)  # Yellow
text_bold=$(tput bold)      # Bold
text_reset=$(tput sgr0)     # Reset your text

function log_error {
    echo "${text_bold}${text_red}[!] ${1}${text_reset}"
}

function log_warn {
    echo "${text_bold}${text_yellow}[-] ${1}${text_reset}"
}

function log_success {
    echo "${text_bold}${text_green}[+] ${1}${text_reset}"
}


readonly ENV_DIR=venv
readonly ENV_PWD_FILE="$ENV_DIR/pwd"

# python virtual environment use hardcoded path that cause problems if the venv is activated
# from a different context such as a container with a different mount namespace.
if [[ -f "$ENV_PWD_FILE" ]]; then
    venv_pwd=$(cat "$ENV_PWD_FILE")
    if [[ "$venv_pwd" != "$PWD" ]]; then
        log_warn "Found existing environment that was apparently created from a different mount namespace, recreating..."
        rm -rf "$ENV_DIR"
    else
        log_success "Found existing environment at $ENV_DIR"
        log_success "Please run \"source $ENV_DIR/bin/activate\" in order to activate the virtual environment"
        exit 0
    fi
fi

log_success "Preparing environment..."

sudo apt-get install -y libpq-dev

python3 -m venv "$ENV_DIR"
echo -n "$PWD" > "$ENV_PWD_FILE"
source $ENV_DIR/bin/activate

pip3 install psycopg2-binary
pip3 install -r requirements.txt

log_success "Successfully prepared environment, please run \"source $ENV_DIR/bin/activate\" to enable it."
