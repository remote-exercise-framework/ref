#!/bin/bash

set -e

mkdir -p data

function usage {
cat <<EOF
Usage:
$0 <cmd>

Commands:
    build:
        Build all images.
    up:
        Start all serviceses.
            --debug
            Enables debug mode. This causes exception to be printed
            on the webinterface. Use this only for development.
            --maintenance
    - down
    - logs#

EOF
exit 1
}

if [[ $# -lt 1 ]]; then
    usage
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


function build {
    #Build the base image for all exercises
    (
        echo "=> Building docker base image"
        cd 'ref-docker-base'
        ./build.sh
    )
    (
        echo "=> Building container"
        docker-compose build
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

function ps {
    docker-compose ps
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
        down $@
    ;;
    logs)
        log $@
    ;;
    stop)
        stop $@
    ;;
    ps)
        ps $@
    ;;
    *)
        echo "$cmd is not a valid command"
        usage
    ;;
esac