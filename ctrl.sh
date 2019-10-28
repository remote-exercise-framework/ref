#!/bin/bash

set -e

mkdir data

function usage {
cat <<EOF
Usage:
$0 <cmd>

Commands:
    - build
    - up
    - down
    - logs#

EOF
exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

if [[ ! -f '.env' ]]; then
    echo "Please copy template.env to .env and adapt the values"
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
            ;;
            *)
                echo "Invalid arg $1"
                usage
            ;;
        esac
        shift
    done

    if [[ "$debug" == 'true' ]]; then
        export DEBUG=1
    fi

    docker-compose up -d
}

function down {
    docker-compose down
}

function log {
    docker-compose logs $@
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
    *)
        echo "$cmd is not a valid command"
        usage
    ;;
esac