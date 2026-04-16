#!/usr/bin/env bash

set -e
set -o pipefail

mkdir -p data

function txt {
    case "$1" in
        bold) tput bold 2>/dev/null || true ;;
        reset) tput sgr0 2>/dev/null || true ;;
        red) tput setaf 1 2>/dev/null || true ;;
        green) tput setaf 2 2>/dev/null || true ;;
        yellow) tput setaf 3 2>/dev/null || true ;;
    esac
}

function txt_bold {
  txt bold
}

function txt_reset {
  txt reset
}

function txt_red {
  txt red
}

function txt_green {
  txt green
}

function txt_yellow {
  txt yellow
}

function info { echo "$(txt bold)$(txt green)[+] $*$(txt reset)"; }
function error { echo "$(txt bold)$(txt red)[!] $*$(txt reset)"; }
function warning { echo "$(txt bold)$(txt yellow)[!] $*$(txt reset)"; }

function execute_cmd {
    info "* $*"
    "$@"
}

function usage {
cat <<EOF
Usage:
  $0 <command> [OPTIONS...]

Commands:
  build
      Build and pull all images, including the docker base image.

  update
      Update the repository and all submodules.

  up [OPTIONS...]
      Start all services.
      Options:
        --debug               Enable debug mode (prints exceptions on web interface).
        --debug-toolbar       Enable the debug toolbar (never use in production).
        --maintenance         Only allow admin users to login.
        --disable-telegram    Disable error reporting via telegram.
        --hot-reloading       Enable hot reloading of the web server (Python)
                              and of the spa-frontend container (Vite HMR).

  down
      Stop and delete all services and networks. Disconnects all users and orphans running instances.

  stop
      Stop all services without removing the associated containers.

  restart
      Restart all services (disconnects currently connected users).

  restart-web
      Restart only the web interface (users stay connected via SSH).

  ps
      List all running containers.

  top
      List all processes running inside the containers.

  logs [-f]
      Print the logs of all services.
      -f    Follow log output and print incoming messages.

  flask-cmd <args>
      Run a Flask CLI command, e.g.:
        flask-cmd db init
        flask-cmd db migrate
        flask-cmd db upgrade

  db-migrate
      Run Flask database migration.

  db-init
      Initialize the Flask database.

  db-upgrade
      Upgrade the Flask database.

  --help
      Show this help message and exit.

EOF
}

function docker_subnet_warning {
txt_yellow
txt_bold
cat <<EOF
You should consider adding more subnets to Docker, thus
we are able to create enough instances of each exercise.

cat /etc/docker/daemon.json
{
        "default-address-pools":[
                {"base":"172.16.0.0/16","size":24},
                {"base":"172.17.0.0/16","size":24},
                {"base":"172.18.0.0/16","size":24},
                {"base":"172.19.0.0/16","size":24},
                {"base":"172.20.0.0/16","size":24}
        ]
}
EOF
txt_reset
echo ""
}

# Check if the environment has all features we expect and that the framework has been cloned properly.

function has_binary {
    command -v $1 >/dev/null 2>&1
    return $?
}

function has_python_module {
    pip3 show "$1" >/dev/null 2>&1
    return $?
}

if [[ $# -lt 1 ]]; then
    error "Not enough arguments"
    usage
    exit 1
fi

submodules=(
    "ref-docker-base/ref-utils/README.md"
    "webapp/ref/static/ace-builds/README.md"
)

# ref-linux is only needed for production, not for building/testing
if [[ -z "${REF_CI_RUN:-}" ]]; then
    submodules+=("ref-linux/README")
fi

for m in "${submodules[@]}"; do
    if [[ ! -f "$m" ]]; then
        error "Failed to find all required submodules!"
        error "Please run: git submodule update --init --recursive"
        error "For further notice, consult the README.md."
        exit 1
    fi
done

# TODO: Check if custom kernel is used.


if ! has_binary "docker"; then
    error "Please install docker!"
    exit 1
fi

# Check if cgroup freezer is used.
container_id=$(docker run -dt --rm alpine:latest sh -c "sleep 60")
if ! docker pause "$container_id" > /dev/null ; then
    error "It looks like your current kernel does not support the cgroup freezer."
    error "The feature is required, please update your kernel!"
    docker rm -f "$container_id" > /dev/null
    exit 1
fi
docker rm -f "$container_id" > /dev/null

cgroup_version="$(docker system info | grep "Cgroup Version" | cut -d ':' -f 2 | tr -d ' ')"
if [[ "$cgroup_version" != 2 ]]; then
    error "docker system info report that you are using an unsupported cgroup version ($cgroup_version)"
    error "We require cgroup v2 which should be the default on more recent distributions."
    error "In order to force the kernel to use v2, you may append systemd.unified_cgroup_hierarchy=1"
    error "to GRUB_CMDLINE_LINUX in /etc/default/grub."
    error "However, it is perferable to update your distribution since it likely missen additional features."
    exit 1
fi

if has_binary docker-compose; then
    DOCKER_COMPOSE="docker-compose"
elif docker compose version > /dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    error "Please install Docker Compose!"
    exit 1
fi

if ! has_binary "jq"; then
    error "Please install jq (apt install -y jq)"
    exit 1
fi

if ! has_binary "pip3"; then
    error "Please install pip3 (apt install -y python3-pip)"
    exit 1
fi

if ! has_python_module "jinja2"; then
     error "Please install jinja2 (apt install -y python3-jinja2)"
     exit 1
fi

#Check the .env files used to parametrize the docker-compose file.
ENV_SETTINGS_FILE="settings.env"
YAML_SETTINGS_FILE="settings.yaml"

# First-run bootstrap: if no configuration exists yet, run prepare.py to
# generate settings.yaml (with secure random secrets), settings.env,
# docker-compose.yml, and the container SSH host keys. prepare.py refuses to
# run if settings.yaml already exists, so this branch only triggers on a
# fresh setup.
if [[ ! -f $YAML_SETTINGS_FILE && ! -f $ENV_SETTINGS_FILE ]]; then
    info "No configuration found, running ./prepare.py for first-run setup"
    if ! ./prepare.py; then
        error "Failed to run prepare.py"
        exit 1
    fi
fi

if [[ ! -f $YAML_SETTINGS_FILE || ! -f $ENV_SETTINGS_FILE ]]; then
    error "Configuration is incomplete: expected both $YAML_SETTINGS_FILE and $ENV_SETTINGS_FILE."
    error "Delete any leftover file and re-run ./prepare.py to regenerate from scratch."
    exit 1
fi

if [[ ! -f "docker-compose.yml" ]]; then
    error "docker-compose.yml is missing. Delete $YAML_SETTINGS_FILE and re-run ./prepare.py to regenerate it."
    exit 1
fi

if [[ ! -f "container-keys/root_key" || ! -f "container-keys/user_key" ]]; then
    error "Container SSH keys are missing. Delete $YAML_SETTINGS_FILE and re-run ./prepare.py to regenerate them."
    exit 1
fi

# shellcheck disable=SC1090
source "$ENV_SETTINGS_FILE"
if [[ -z "$DOCKER_GROUP_ID" ]]; then
    error "Please set DOCKER_GROUP_ID in $ENV_SETTINGS_FILE to your docker group ID (getent group docker)"
    exit 1
fi

if [[ "$(getent group docker | cut -d ':' -f 3)" != "$DOCKER_GROUP_ID" ]]; then
    error "DOCKER_GROUP_ID in $ENV_SETTINGS_FILE does not match the local docker group ID."
    error "Use the id command to get the correct group ID."
    exit 1
fi

if [[ -z "$SSH_HOST_PORT" ]]; then
    error "Please set SSH_HOST_PORT in $ENV_SETTINGS_FILE to the port the entry ssh server should be expose on the host"
    exit 1
fi

if [[ -z "$HTTP_HOST_PORT" ]]; then
    error "Please set HTTP_HOST_PORT in $ENV_SETTINGS_FILE to the port the entry ssh server should be expose on the host"
    exit 1
fi

# The spa-frontend service is gated behind the `dev` compose profile so it
# is only started when --hot-reloading is active. Activate the profile for
# every ctrl.sh subcommand so profile-gated services can still be
# built/stopped/inspected; the `up` function unsets this again for prod
# mode so spa-frontend does not get started there.
export COMPOSE_PROFILES=dev

if [[ -z "$SECRET_KEY" ]]; then
    error "Please set SECRET_KEY in $ENV_SETTINGS_FILE to a random string"
    exit 1
fi

if [[ -z "$SSH_TO_WEB_KEY" ]]; then
    error "Please set SSH_TO_WEB_KEY in $ENV_SETTINGS_FILE to a random string"
    exit 1
fi

if [[ -z "$POSTGRES_PASSWORD" ]]; then
    error "Please set POSTGRES_PASSWORD in $ENV_SETTINGS_FILE to a random string"
    exit 1
fi

if [[ -z "$ADMIN_PASSWORD" ]]; then
    error "Please set ADMIN_PASSWORD in $ENV_SETTINGS_FILE to a random string"
    exit 1
fi

#Check whether we have enough docker subnets configured.
if [[ ! -f "/etc/docker/daemon.json" ]]; then
    docker_subnet_warning
else
    if ! grep -q "default-address-pools" /etc/docker/daemon.json; then
        warning "It looks like that there are no default-address-pools defined in your /etc/docker/daemon.json."
        warning "This may cause you to run out of addresses depending on the number of deployed instances."
        docker_subnet_warning
    else
        #TODO: We are just counting the number of configured nets, not their size
        net_cnt="$(cat /etc/docker/daemon.json | jq '."default-address-pools"' | grep base | wc -l)"
        if [[ $net_cnt -lt 4 ]]; then
            docker_subnet_warning
        fi
    fi
fi


function update {
    (
        # Check for uncommitted changes, ignoring untracked files
        # -n tests if string length is non-zero
        # git status --porcelain -uno returns modified files (excluding untracked)
        if [[ -n "$(git status --porcelain -uno)" ]]; then
            error "There are uncommitted changes in the main repository. Please commit or stash them first."
            exit 1
        fi

        # Check submodules for uncommitted changes, suppressing "Entering..." messages
        if [[ -n "$(git submodule foreach --quiet git status --porcelain -uno)" ]]; then
            error "There are uncommitted changes in one or more submodules. Please commit or stash them first."
            exit 1
        fi

        info "=> Updating repository"
        git pull
        info "=> Updating submodules"
        git submodule update --recursive
    )
}

function build {
    #Build the base image for all exercises
    (
        info "=> Building docker base image"
        cd 'ref-docker-base'
        ./build.sh "$@"
    )
    (
        info "=> Building release container"
        execute_cmd $DOCKER_COMPOSE -p ref --env-file $ENV_SETTINGS_FILE build "$@"
        execute_cmd $DOCKER_COMPOSE -p ref --env-file $ENV_SETTINGS_FILE pull
    )
}

function check_submodule_sync {
    # Check if submodules match the commits tracked by the main repo
    local out_of_sync=()
    while IFS= read -r line; do
        # git submodule status prefixes with '-' (not init), '+' (wrong commit), or ' ' (ok)
        if [[ "$line" == +* ]]; then
            # Extract submodule path (second field)
            local path
            path=$(echo "$line" | awk '{print $2}')
            out_of_sync+=("$path")
        fi
    done < <(git submodule status --recursive)

    if [[ ${#out_of_sync[@]} -gt 0 ]]; then
        warning "The following submodules do not match the commits tracked by the repository:"
        for sm in "${out_of_sync[@]}"; do
            warning "  - $sm"
        done
        read -r -p "$(txt bold)$(txt yellow)[?] Update submodules to match? [Y/n] $(txt reset)" answer
        if [[ -z "$answer" || "$answer" =~ ^[Yy] ]]; then
            info "=> Updating submodules"
            git submodule update --init --recursive
        else
            warning "Continuing with mismatched submodules."
        fi
    fi
}

function up {
    check_submodule_sync
    export REAL_HOSTNAME="$(hostname)"
    export DEBUG=false
    export DISABLE_RESPONSE_CACHING=false
    export MAINTENANCE_ENABLED=false
    export DISABLE_TELEGRAM=false
    export DEBUG_TOOLBAR=false
    export HOT_RELOADING=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            '--debug')
                export DEBUG=true
                shift
            ;;
            '--disable-response-caching')
                export DISABLE_RESPONSE_CACHING=true
                shift
            ;;
            '--maintenance')
                export MAINTENANCE_ENABLED=true
                shift
            ;;
            '--disable-telegram')
                export DISABLE_TELEGRAM=true
                shift
            ;;
            '--debug-toolbar')
                export DEBUG_TOOLBAR=true
                shift
            ;;
            '--hot-reloading')
                export HOT_RELOADING=true
                shift
            ;;
            *)
            #Pass unknown flags to docker-compose
            break
            ;;
        esac
    done

    if [[ "$HOT_RELOADING" != "true" ]]; then
        # Prod mode: skip the profile-gated spa-frontend service. Caddy
        # serves the baked SPA bundle from the frontend-proxy image.
        unset COMPOSE_PROFILES
    fi

    execute_cmd $DOCKER_COMPOSE -p ref --env-file $ENV_SETTINGS_FILE up "$@"
}

function down {
    execute_cmd $DOCKER_COMPOSE -p ref --env-file $ENV_SETTINGS_FILE down
}

function log {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref logs "$@"
}

function stop {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref stop
}

function restart {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref restart "$@"
}

function ps {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref ps "$@"
}

function top {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref top "$@"
}

function db_migrate {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref run --rm web bash -c "DB_MIGRATE=1 FLASK_APP=ref python3 -m flask db migrate"
}

function db_init {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref run --rm web bash -c "DB_MIGRATE=1 FLASK_APP=ref python3 -m flask db init"
}

function db_upgrade {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref run --rm web bash -c "DB_MIGRATE=1 FLASK_APP=ref python3 -m flask db upgrade"
}

function flask-cmd {
    execute_cmd $DOCKER_COMPOSE --env-file $ENV_SETTINGS_FILE -p ref run --rm web bash -c "FLASK_APP=ref python3 -m flask $*"
}

cmd="$1"
shift

case "$cmd" in
    build)
        build "$@"
    ;;
    update)
        update "$@"
    ;;
    up)
        up "$@"
    ;;
    down)
        down "$@"
    ;;
    logs)
        log "$@"
    ;;
    stop)
        stop "$@"
    ;;
    restart)
        restart "$@"
    ;;
    restart-web)
        restart web "$@"
    ;;
    ps)
        ps "$@"
    ;;
    top)
        top "$@"
    ;;
    flask-cmd)
        flask-cmd "$@"
    ;;
    db-migrate)
        db_migrate "$@"
    ;;
    db-init)
        db_init "$@"
    ;;
    db-upgrade)
        db_upgrade "$@"
    ;;
    --help)
        usage
        exit 0
    ;;
    *)
        error "$cmd is not a valid command"
        usage
        exit 1
    ;;
esac
