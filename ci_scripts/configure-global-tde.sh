#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
INSTALL_DIR="$SCRIPT_DIR/../../pginst"
DATA_DIR=$INSTALL_DIR/data

cd "$SCRIPT_DIR/.."

export TDE_MODE=1
export PATH=$INSTALL_DIR/bin:$PATH
export PGDATA="${1:-$DATA_DIR}"
export PGPORT="${2:-5432}"

PG_VERSION=$(pg_config --version | sed -n 's/PostgreSQL \([0-9]*\).*/\1/p')

# Replace tools so that postgres' testsuite will use the modified ones
cp "$INSTALL_DIR/bin/pg_tde_basebackup" "$INSTALL_DIR/bin/pg_basebackup"
cp "$INSTALL_DIR/bin/pg_tde_checksums" "$INSTALL_DIR/bin/pg_checksums"
cp "$INSTALL_DIR/bin/pg_tde_resetwal" "$INSTALL_DIR/bin/pg_resetwal"
cp "$INSTALL_DIR/bin/pg_tde_rewind" "$INSTALL_DIR/bin/pg_rewind"
cp "$INSTALL_DIR/bin/pg_tde_waldump" "$INSTALL_DIR/bin/pg_waldump"

if [ -d "$PGDATA" ]; then
    if pg_ctl -D "$PGDATA" status -o "-p $PGPORT" >/dev/null; then
        pg_ctl -D "$PGDATA" stop -o "-p $PGPORT"
    fi

    rm -rf "$PGDATA"
fi

OPTS='--set shared_preload_libraries=pg_tde'

if [ "$PG_VERSION" -ge 18 ]; then
    OPTS+=' --set io_method=sync'
fi

initdb -D "$PGDATA" $OPTS

pg_ctl -D "$PGDATA" start -o "-p $PGPORT"

psql postgres -f "$SCRIPT_DIR/tde_setup_global.sql" -v ON_ERROR_STOP=on

pg_ctl -D "$PGDATA" restart -o "-p $PGPORT"
