#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
PG_CONFIG="$SCRIPT_DIR/../../pginst/bin/pg_config"

cd "$SCRIPT_DIR/.."

export CFLAGS="-Werror -O2"
make PG_CONFIG="$PG_CONFIG" install -j
