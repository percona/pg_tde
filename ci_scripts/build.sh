#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
PG_CONFIG="${PG_INSTALL_DIR:-$SCRIPT_DIR/../../pginst}/bin/pg_config"
BUILD_TYPE=
ARGS=
CLANG_SAN_ARGS=

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
        case "$CC" in *clang*) CLANG_SAN_ARGS=",'-fno-sanitize=function'" ;; esac
        ARGS+=" -Dc_args=['-fsanitize=address','-fsanitize=undefined'$CLANG_SAN_ARGS,'-fno-omit-frame-pointer','-fno-inline-functions']"
        ARGS+=" -Dc_link_args=['-fsanitize=address','-fsanitize=undefined']"
        # vptr's UBSan runtime lives in the C++-only ubsan_standalone_cxx library,
        # which the C postgres backend that dlopens pg_tde.so does not link, so it
        # is disabled here to avoid an undefined __ubsan_vptr_type_cache at load.
        ARGS+=" -Dcpp_args=['-fsanitize=address','-fsanitize=undefined','-fno-sanitize=vptr'$CLANG_SAN_ARGS,'-fno-omit-frame-pointer','-fno-inline-functions']"
        ARGS+=" -Dcpp_link_args=['-fsanitize=address','-fsanitize=undefined']"
        ;;

    exec-backend)
        echo "Building with exec-backend option"
        BUILD_TYPE=debugoptimized
        ;;

    *)
        echo "Unknown build type: $1"
        echo "Please use one of the following: debug, debugoptimized, coverage, sanitize, exec-backend"
        exit 1
        ;;
esac

if [ -f "$PG_SOURCE_DIR/.git-revision" ]; then
    echo "PostgreSQL revision: $(cat "$PG_SOURCE_DIR/.git-revision")"
fi

echo "# pg_config"
"$PG_CONFIG"

cd "$SCRIPT_DIR/.."
meson setup --buildtype="$BUILD_TYPE" -Dpg_config="$PG_CONFIG" -Dwerror=true $ARGS ../build
meson install -C ../build
