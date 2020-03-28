#!/bin/bash

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
    echo "$(txt_bold)$(txt_green)$1$(txt_reset)"
}

function error {
    echo "$(txt_bold)$(txt_red)$1$(txt_reset)"
}

function warning {
    echo "$(txt_bold)$(txt_yellow)$1$(txt_reset)"
}


function usage {
cat <<EOF
Usage:
$0 <Command> [OPTIONS...]

Commands:
    build
        Build and pull all images including the docker based image.

    up
        Start all serviceses.
            --debug
            Enables debug mode. This causes exception to be printed
            on the webinterface. Use this only for development.
            --maintenance
            Only allow admin users to login.

    stop
        Stop all services without removing the associated containers.

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
        Run a flask CLI command like:
            db init
            db migrate
            db upgrade
            ...
EOF
}

function docker_subnet_warning {
txt_yellow
txt_bold
cat <<EOF
You should consider adding more subnets to docker, thus
we are able to create enough instances of each task.

cat /etc/docker/daemon.json 
{
        "default-address-pools":[
                {"base":"172.80.0.0/16","size":24},
                {"base":"172.81.0.0/16","size":24},
                {"base":"172.82.0.0/16","size":24},
                {"base":"172.83.0.0/16","size":24},
                {"base":"172.84.0.0/16","size":24}
        ]
}
EOF
txt_reset
echo ""
}

function has_binary {
    command -v $1 >/dev/null 2>&1
    return $?
}

if [[ $# -lt 1 ]]; then
    error "Not enough arguments"
    usage
    exit 1
fi

if ! has_binary "docker"; then
    error "Please install docker!"
    exit 1
fi

if ! has_binary docker-compose; then
    error "Please install docker-compose!"
    exit 1
fi

if ! has_binary jq; then
    error "Please install jq"
    exit 1
fi

if ! has_binary "kpatch" || ! has_binary "kpatch-build"; then
    warning "kpatch or kpatch-build are not installed but are required for disabling"
    warning "ASLR on a per exercise basis. See aslr-patch for further instructions."
    echo ""
else
    pushd aslr-patch
    set +e
    ./enable.sh
    if [[ $? != 0 ]]; then
        warning "Failed to load ASLR patch."
        warning "Disabling ASLR for setuid binaries will not work..."
    fi
    set -e
    popd
fi


#Check the .env files used to parametrize the docker-compose file.

if [[ ! -f '.env' ]]; then
    error "Please copy template.env to .env and adapt the values"
    exit 1
fi

source .env
if [[ -z "$DOCKER_GROUP_ID" ]]; then
    error "Please set DOCKER_GROUP_ID in .env to your docker group ID"
    exit 1
fi

if [[ "$(getent group docker | cut -d ':' -f 3)" != "$DOCKER_GROUP_ID" ]]; then
    error "DOCKER_GROUP_ID in .env does not match the local docker group ID."
    error "Use the id command to get the correct group ID."
    exit 1
fi

if [[ -z "$SSH_HOST_PORT" ]]; then
    error "Please set SSH_HOST_PORT in .env to the port the entry ssh server should be expose on the host"
    exit 1
fi

if [[ -z "$HTTP_HOST_PORT" ]]; then
    error "Please set HTTP_HOST_PORT in .env to the port the entry ssh server should be expose on the host"
    exit 1
fi

if [[ -z "$SECRET_KEY" ]]; then
    error "Please set SECRET_KEY in .env to a random string"
    exit 1
fi

if [[ -z "$SSH_TO_WEB_KEY" ]]; then
    error "Please set SSH_TO_WEB_KEY in .env to a random string"
    exit 1
fi

if [[ -z "$POSTGRES_PASSWORD" ]]; then
    error "Please set POSTGRES_PASSWORD in .env to a random string"
    exit 1
fi

if [[ -z "$PGADMIN_HTTP_PORT" ]]; then
    error "Please set PGADMIN_HTTP_PORT in .env to a port PGADMIN should be exposed on the host"
    exit 1
fi

if [[ -z "$PGADMIN_DEFAULT_PASSWORD" ]]; then
    error "Please set PGADMIN_DEFAULT_PASSWORD in .env to a random string"
    exit 1
fi

if [[ -z "$REDIS_KEY" ]]; then
    error "Please set REDIS_KEY in .env to a random string"
    exit 1
fi

if [[ -z "$ADMIN_PASSWORD" ]]; then
    error "Please set ADMIN_PASSWORD in .env to a random string"
    exit 1
fi


if [[ ! -d "./data/redis-db" || "$(stat -c '%u' './data/redis-db')" != "1001" ]]; then
    info "=> Fixing redis DB permissinos, requesting super user access..."
    sudo mkdir -p './data/redis-db'
    sudo chown 1001:1001 -R './data/redis-db'
fi

if [[ ! -d "./data/pgadmin" || "$(stat -c '%u' './data/pgadmin')" != "5050" ]]; then
    info "=> Fixing pgadmin DB permissinos, requesting super user access..."
    sudo mkdir -p './data/pgadmin'
    sudo chown 5050:5050 -R './data/pgadmin'
fi


#Check whether we have enough docker subnets configured.
if [[ ! -f "/etc/docker/daemon.json" ]]; then
    docker_subnet_warning
else
    #FIXME: Just counting the number of configured nets, not their size
    net_cnt="$(cat /etc/docker/daemon.json | jq '."default-address-pools"' | grep base | wc -l)"
    if [[ $net_cnt -lt 4 ]]; then
        docker_subnet_warning
    fi
fi


python generate-configs.py

function build {
    #Build the base image for all exercises
    (
        info "=> Building docker base image"
        cd 'ref-docker-base'
        ./build.sh $@
    )
    (
        info "=> Building release container"
        docker-compose -p ref build $@
        docker-compose -p ref pull
    )
    (
        info "=> Building test container"
        docker-compose -f docker-compose-testing.yml -p ref-testing build $@
        docker-compose -f docker-compose-testing.yml -p ref-testing pull
    )
}

function up {
    while [[ $# -gt 0 ]]; do
        case $1 in
            '--debug')
                debug=true
                shift
            ;;
            '--maintenance')
                maintenance=true
                shift
            ;;
            *)
            #Pass unknown flags to docker-compose
            break
            ;;
        esac
    done

    if [[ "$debug" == 'true' ]]; then
        export DEBUG=1
    fi

    if [[ "$maintenance" == 'true' ]]; then
        export MAINTENANCE_ENABLED=1
    fi

    docker-compose -p ref up $@
}

function down {
    docker-compose -p ref down
}

function log {
    docker-compose -p ref logs $@
}

function stop {
    docker-compose -p ref stop
}

function restart {
    docker-compose -p ref restart $@
}

function ps {
    docker-compose -p ref ps $@
}

function flask-cmd {
    info "FLASK_APP=ref python3 -m flask $*"
    docker-compose -p ref exec web bash -c "FLASK_APP=ref python3 -m flask $*"
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

function up_testing {
    docker-compose -f docker-compose-testing.yml -p ref-testing up $@
}

function down_testing {
    docker-compose -f docker-compose-testing.yml -p ref-testing down $@
}

function run_tests {
    docker exec -it ref-testing_web_1 /bin/bash -c 'pytest --cov=. --cov-report html -v --failed-first  ./test'
}

cmd="$1"
shift

case "$cmd" in
    build)
        build $@
    ;;
    up)
        up $@
    ;;
    down)
        are_you_sure || exit 0
        down $@
    ;;
    logs)
        log $@
    ;;
    stop)
        are_you_sure || exit 0
        stop $@
    ;;
    restart)
        are_you_sure || exit 0
        restart $@
    ;;
    restart-web)
        are_you_sure || exit 0
        restart web $@
    ;;
    ps)
        ps $@
    ;;
    flask-cmd)
        flask-cmd $@
    ;;
    run-tests)
        run_tests $@
    ;;
    up-testing)
        up_testing $@
    ;;
    down-testing)
        down_testing $@
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