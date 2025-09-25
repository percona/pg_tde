#!/bin/bash

SCRIPT_DIR=$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)

set -e

PGDIR=$1
PGVERSION=$2
TARGET_DIR=$SCRIPT_DIR/../fetools/pg$PGVERSION

rm -rf "$TARGET_DIR"
mkdir "$TARGET_DIR"
cp -R "$PGDIR/src/bin/pg_basebackup" "$TARGET_DIR"
cp -R "$PGDIR/src/bin/pg_checksums" "$TARGET_DIR"
cp -R "$PGDIR/src/bin/pg_resetwal" "$TARGET_DIR"
cp -R "$PGDIR/src/bin/pg_rewind" "$TARGET_DIR"
cp -R "$PGDIR/src/bin/pg_waldump" "$TARGET_DIR"
cp -R "$PGDIR/src/backend/access/rmgrdesc" "$TARGET_DIR"
cp -R "$PGDIR/src/backend/access/transam/xlogreader.c" "$TARGET_DIR"
cp -R "$PGDIR/src/backend/access/transam/xlogstats.c" "$TARGET_DIR"
mkdir "$TARGET_DIR/include"
cp -R "$PGDIR/src/include/backup" "$TARGET_DIR/include"
find "$TARGET_DIR" -not -name '*.c' -not -name '*.h' -type f -delete
