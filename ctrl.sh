#!/bin/bash

set -e

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

function usage {
cat <<EOF
Usage:
$0 <cmd>

Commands:
    build:
        Build and pull all images including the docker based image.
    up:
        Start all serviceses.
            --debug
            Enables debug mode. This causes exception to be printed
            on the webinterface. Use this only for development.
            --maintenance
    stop:
    restart-web
    restart
    down
    logs
    cmd
    flask-cmd
EOF
exit 1
}

function has_binary {
    command -v $1 >/dev/null 2>&1
    return $?
}

if [[ $# -lt 1 ]]; then
    usage
fi

if ! has_binary docker; then
    echo "Please install docker!"
    exit 1
fi

if ! has_binary docker-compose; then
    echo "Please install docker-compose!"
    exit 1
fi

if ! has_binary "kpatch" || !has_binary "kpatch-build"; then
    echo "$(txt_bold)$(txt_yellow)kpatch or kpatch-build are not installed but are required for disabling"
    echo "ASLR on a per exercise basis. See aslr-patch for further instructions.$(txt_reset)"
    exit 1
fi

#Check the .env files used to parametrize the docker-compose file.

if [[ ! -f '.env' ]]; then
    echo "Please copy template.env to .env and adapt the values"
    exit 1
fi

source .env
if [[ -z "$DOCKER_GROUP_ID" ]]; then
    echo "Please set DOCKER_GROUP_ID in .env to your docker group ID"
    exit 1
fi

if [[ "$(getent group docker | cut -d ':' -f 3)" != "$DOCKER_GROUP_ID" ]]; then
    echo "DOCKER_GROUP_ID in .env does not match the local docker group ID"
    exit 1
fi

if [[ -z "$SSH_HOST_PORT" ]]; then
    echo "Please set SSH_HOST_PORT in .env to the port the entry ssh server should be expose on the host"
    exit 1
fi

if [[ -z "$HTTP_HOST_PORT" ]]; then
    echo "Please set HTTP_HOST_PORT in .env to the port the entry ssh server should be expose on the host"
    exit 1
fi

if [[ -z "$SECRET_KEY" ]]; then
    echo "Please set SECRET_KEY in .env to a random string"
    exit 1
fi

if [[ -z "$SSH_TO_WEB_KEY" ]]; then
    echo "Please set SSH_TO_WEB_KEY in .env to a random string"
    exit 1
fi

if [[ -z "$POSTGRES_PASSWORD" ]]; then
    echo "Please set POSTGRES_PASSWORD in .env to a random string"
    exit 1
fi

if [[ -z "$PGADMIN_HTTP_PORT" ]]; then
    echo "Please set PGADMIN_HTTP_PORT in .env to a port PGADMIN should be exposed on the host"
    exit 1
fi

if [[ -z "$PGADMIN_DEFAULT_PASSWORD" ]]; then
    echo "Please set PGADMIN_DEFAULT_PASSWORD in .env to a random string"
    exit 1
fi




function build {
    #Build the base image for all exercises
    (
        echo "=> Building docker base image"
        cd 'ref-docker-base'
        ./build.sh $@
    )
    (
        echo "=> Building container"
        docker-compose build $@
        docker-compose pull
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

    docker-compose up $@
}

function down {
    docker-compose down
}

function log {
    docker-compose logs $@
}

function stop {
    docker-compose stop
}

function restart {
    docker-compose restart $@
}

function ps {
    docker-compose ps $@
}

function flask-cmd {
    echo "FLASK_APP=ref python3 -m flask $@"
    docker-compose exec web bash -c "FLASK_APP=ref python3 -m flask $*"
}

function are_you_sure {
    echo -n "Are you sure? [y/n]"
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
    *)
        echo "$cmd is not a valid command"
        usage
    ;;
esac