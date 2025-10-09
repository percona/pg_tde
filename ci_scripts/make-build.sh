#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
PG_CONFIG="$SCRIPT_DIR/../../pginst/bin/pg_config"

cd "$SCRIPT_DIR/.."

case "$1" in
    debug)
        echo "Building with debug option"
        ;;

    debugoptimized)
        echo "Building with debugoptimized option"
        export CFLAGS="-O2"
        ;;

    sanitize)
        echo "Building with sanitize option"
        export CFLAGS="-fsanitize=address -fsanitize=undefined -fno-omit-frame-pointer -fno-inline-functions"
        ;;

    *)
        echo "Unknown build type: $1"
        echo "Please use one of the following: debug, debugoptimized, sanitize"
        exit 1
        ;;
esac

make PG_CONFIG="$PG_CONFIG" install -j
