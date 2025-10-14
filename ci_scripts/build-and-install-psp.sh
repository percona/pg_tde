#!/bin/bash

set -e

ARGS=

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
INSTALL_DIR="$SCRIPT_DIR/../../pginst"
PSP_DIR="$SCRIPT_DIR/../../postgres"

PG_VERSION=$(sed -n "s/PACKAGE_VERSION='\\([0-9]*\\).*/\1/p" "$PSP_DIR/configure")

INSTALL_INJECTION_POINTS=0

case "$1" in
    debug)
        echo "Building with debug option"
        ARGS+=" --enable-cassert"
        INSTALL_INJECTION_POINTS=1
        ;;

    debugoptimized)
        echo "Building with debugoptimized option"
        export CFLAGS="-O2"
        ARGS+=" --enable-cassert"
        INSTALL_INJECTION_POINTS=1
        ;;

    coverage)
        echo "Building with coverage option"
        ARGS+=" --enable-coverage"
        INSTALL_INJECTION_POINTS=1
        ;;

    sanitize)
        echo "Building with sanitize option"
        export CFLAGS="-fsanitize=address -fsanitize=undefined -fno-omit-frame-pointer -fno-inline-functions"
        ;;

    *)
        echo "Unknown build type: $1"
        echo "Please use one of the following: debug, debugoptimized, coverage, sanitize"
        exit 1
        ;;
esac

if [ "$PG_VERSION" -lt 17 ]; then
    INSTALL_INJECTION_POINTS=0
fi

if [ "$INSTALL_INJECTION_POINTS" = 1 ]; then
     ARGS+=" --enable-injection-points"
fi

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    if [ "$PG_VERSION" -ge 17 ]; then
        ARGS+=" --with-liburing"
    fi
    NCPU=$(nproc)
elif [[ "$OSTYPE" == "darwin"* ]]; then
    NCPU=$(sysctl -n hw.ncpu)
fi

cd "$PSP_DIR"

./configure \
   --prefix="$INSTALL_DIR" \
   --enable-debug \
   --enable-tap-tests \
   $ARGS

make install-world -s -j $NCPU

if [ "$INSTALL_INJECTION_POINTS" = 1 ]; then
    # Injection points extension is not built by default
    make install -j -s -C src/test/modules/injection_points
fi
