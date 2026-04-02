#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"

cd "$SCRIPT_DIR/.."

OPTS='--set shared_preload_libraries=pg_tde'

if [ "$1" = sanitize ]; then
    OPTS+=' --set max_stack_depth=8MB'
fi

for i in {1..10}; do
    make PG_CONFIG=../pginst/bin/pg_config installcheck PROVE_TESTS=t/pg_rewind_basic.pl
done

