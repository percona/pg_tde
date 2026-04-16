#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
PG_CONFIG="$SCRIPT_DIR/../../pginst/bin/pg_config"
BUILD_TYPE=
ARGS=

case "$1" in
    debug)
        echo "Building with debug option"
        BUILD_TYPE=$1
        ;;

    debugoptimized)
        echo "Building with debugoptimized option"
        BUILD_TYPE=$1
        ;;

    coverage)
        echo "Building with coverage option"
        BUILD_TYPE=debug
        ARGS+=-Db_coverage=true
        ;;

    sanitize)
        echo "Building with sanitize option"
        BUILD_TYPE=debug
        ARGS+=" -Dc_args=['-fsanitize=address','-fsanitize=undefined','-fno-omit-frame-pointer','-fno-inline-functions']"
        ARGS+=" -Dc_link_args=['-fsanitize=address','-fsanitize=undefined']"
        ;;

    *)
        echo "Unknown build type: $1"
        echo "Please use one of the following: debug, debugoptimized, coverage, sanitize"
        exit 1
        ;;
esac

cd "$SCRIPT_DIR/.."
meson setup --buildtype="$BUILD_TYPE" -Dpg_config="$PG_CONFIG" -Dwerror=true $ARGS ../build
meson install -C ../build
