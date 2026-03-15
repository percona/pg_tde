#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
PG_CONFIG="$SCRIPT_DIR/../../pginst/bin/pg_config"
CFLAGS=

cd "$SCRIPT_DIR/.."

BUILD_TYPE=

case "$1" in
    debug)
        echo "Building with debug option"
        BUILD_TYPE=$1
        ;;

    debugoptimized)
        echo "Building with debugoptimized option"
        BUILD_TYPE=$1
        ;;

    sanitize)
        echo "Building with sanitize option"
        BUILD_TYPE=debug
        CFLAGS+=" -fsanitize=address -fsanitize=undefined -fno-omit-frame-pointer -fno-inline-functions"
        ;;

    *)
        echo "Unknown build type: $1"
        echo "Please use one of the following: debug, debugoptimized, sanitize"
        exit 1
        ;;
esac

"$PG_CONFIG"

export CFLAGS
meson setup --buildtype="$BUILD_TYPE" -Dpg_config="$PG_CONFIG" -Dwerror=true build
cd build
meson install
