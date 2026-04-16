#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"

cd "$SCRIPT_DIR/../../build"

if [ "$1" = sanitize ]; then
    export PG_TEST_INITDB_EXTRA_OPTS='--set max_stack_depth=8MB'
fi

meson test --timeout-multiplier=0 --print-errorlogs
