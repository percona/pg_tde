#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
INSTALL_DIR="${PG_INSTALL_DIR:-$SCRIPT_DIR/../../pginst}"
PG_SOURCE_DIR="${PG_SOURCE_DIR:-$SCRIPT_DIR/../../postgres}"
cd "$SCRIPT_DIR/../"

if ! test -f typedefs.list; then
  echo "typedefs.list doesn't exists, run dump-typedefs.sh first"
  exit 1
fi

# Prebuilt CI images already ship pg_bsd_indent, so only build it when it is
# actually missing.
if ! test -x "$INSTALL_DIR/bin/pg_bsd_indent"; then
  make -C "$PG_SOURCE_DIR"/src/tools/pg_bsd_indent install
fi

export PATH=$PG_SOURCE_DIR/src/tools/pgindent/:$INSTALL_DIR/bin/:$PATH

# Check pg_tde with the fresh list extraxted from the object file
pgindent --typedefs=typedefs.list --excludes=<(echo "subprojects/") "$@" .
