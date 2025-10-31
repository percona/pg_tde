#!/bin/bash

set -e

ADD_FLAGS=

for arg in "$@"
do
    case "$arg" in
        --continue)
            ADD_FLAGS="-k"
            shift;;
    esac
done

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
SRC_DIR="$SCRIPT_DIR/../../postgres"

source "$SCRIPT_DIR/configure-global-tde.sh"

cd "$SRC_DIR"
EXTRA_REGRESS_OPTS="--extra-setup=$SCRIPT_DIR/tde_setup.sql" make -s installcheck-world $ADD_FLAGS PROVE_FLAGS="-e 'perl -I$SCRIPT_DIR/perl -I$SRC_DIR/src/test/perl -MPostgreSQL::Test::TdeCluster'"
