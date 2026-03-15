#!/bin/bash
#
# Fetches typedefs list for PostgreSQL core and merges it with typedefs
# defined in this project.
#
# https://wiki.postgresql.org/wiki/Running_pgindent_on_non-core_code_or_development_code

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
cd "$SCRIPT_DIR/../../build"

if ! test -f pg_tde.so; then
  echo "pg_tde.so doesn't exists, run build.sh first in debug mode"
  exit 1
fi

(
  ../postgres/src/tools/find_typedef .
  wget -q -O - "https://buildfarm.postgresql.org/cgi-bin/typedefs.pl?branch=REL_17_STABLE"
  wget -q -O - "https://buildfarm.postgresql.org/cgi-bin/typedefs.pl?branch=REL_18_STABLE"
) | sort -u > ../src/typedefs.list
