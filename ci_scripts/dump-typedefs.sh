#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
cd "$SCRIPT_DIR/.."

if ! test -f pg_tde.so; then
  echo "pg_tde.so doesn't exists, run make-build.sh first in debug mode"
  exit 1
fi

../postgres/src/tools/find_typedef . > typedefs.list

make update-typedefs
