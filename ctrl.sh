#!/usr/bin/env bash

set -e
set -o pipefail

mkdir -p data

function txt_bold {
  tput bold 2> /dev/null
}

function txt_reset {
  tput sgr0 2> /dev/null
}

function txt_red {
  tput setaf 1 2> /dev/null
}

function txt_green {
  tput setaf 2 2> /dev/null
}

function txt_yellow {
  tput setaf 3 2> /dev/null
}

function info {
    echo "$(txt_bold)$(txt_green)[+] $*$(txt_reset)"
}

function error {
    echo "$(txt_bold)$(txt_red)[!] $*$(txt_reset)"
}

function warning {
    echo "$(txt_bold)$(txt_yellow)[!] $*$(txt_reset)"
}

function execute_cmd {
    info "* $*"
    "$@"
}

function usage {
cat <<EOF
Usage:
$0 <Command> [OPTIONS...]

Commands:
    build
        Build and pull all images including the docker based image.
    update
        Update the repository and all submodules.

    up
        Start all serviceses.
            --debug
            Enables debug mode. This causes exception to be printed
            on the webinterface. Use this only for development.
            --debug-toolbar
            Enable the debug toolbar. This should never be enabled in
            production (not even in the maintenance mode).
            --maintenance
            Only allow admin users to login.
            --disable-telegram
            Disable error reporting via telegram.
            --hot-reloading
            Enable hot reloading of the server if any file expect .html, .js or .sh
            is changed in tree.

    stop
        Stop all services without removing the associated containers.

    ps
        List all running containers.

    top
        List all processes running inside the containers.

    restart-web
        Only restart the webinterface without the other services, thus
        user get not disconnected since the SSH server is left untouched.
        This command can be used to reload changes applied to the webinterface.

    restart
        Restart all services. This will disconnect currently connected users.

    down
        Stop and delete all services and networks. This operation disconnects all users
        and orphans all currently running instances since the network connecting them
        with the ssh entry server is deleted. Consequently, all instances must be recreated
        on demand when a user first connects. In general this command is only needed if
        changes where applied to the container composition itself.

    logs
        Print the logs of all services on stdout.
            -f
            Follow to the log output and print incoming messages.

    flask-cmd
        Run a flask CLI command, e.g.,
            flask-cmd db init
            flask-cmd db migrate
            flask-cmd db upgrade
            ...
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
    "ssh-wrapper/openssh-portable/README.md"
    "ref-docker-base/ref-utils/README.md"
    "ref-linux/README"
    "webapp/ref/static/ace-builds/README.md"
)

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

if [[ ! -f $ENV_SETTINGS_FILE ]]; then
    error "Please copy template.env to $ENV_SETTINGS_FILE and adapt the values"
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

# Generate docker-compose files and generate keys.
if ! ./prepare.py; then
    error "Failed to run prepare.py"
    exit 1
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

function up {
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

function are_you_sure {
    info "Are you sure? [y/n]"
    read yes_no
    if [[ "$yes_no" == "y" ]]; then
        return 0
    else
        return 1
    fi
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
        are_you_sure || exit 0
        down "$@"
    ;;
    logs)
        log "$@"
    ;;
    stop)
        are_you_sure || exit 0
        stop "$@"
    ;;
    restart)
        are_you_sure || exit 0
        restart "$@"
    ;;
    restart-web)
        are_you_sure || exit 0
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
    run-tests)
        run_tests "$@"
    ;;
    up-testing)
        up_testing "$@"
    ;;
    down-testing)
        down_testing "$@"
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
