#!/bin/bash

set -e
SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"

cd $SCRIPT_DIR/..

../pginst/bin/pg_ctl -D regress_install -l regress_install.log init -o '--set shared_preload_libraries=pg_tde'

if [ "$1" = "sanitize" ]; then
	echo 'max_stack_depth=8MB' >> regress_install/postgresql.conf
fi

../pginst/bin/pg_ctl -D regress_install -l regress_install.log start

make PG_CONFIG="../pginst/bin/pg_config" installcheck

../pginst/bin/pg_ctl -D regress_install stop
