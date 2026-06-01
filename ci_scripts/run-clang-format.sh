#!/bin/bash

# Format the C++ sources  with clang-format.
#
# C sources and headers are handled by pgindent instead; see run-pgindent.sh.

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"
cd "$SCRIPT_DIR/.."

CLANG_FORMAT="${CLANG_FORMAT:-clang-format}"

FILES=$(git ls-files 'src/**/*.cpp')

if test -z "$FILES"; then
	echo "no C++ sources found"
	exit 0
fi

if test "$1" = "--check"; then
	status=0
	for f in $FILES; do
		if ! diff -u "$f" <("$CLANG_FORMAT" "$f") >/dev/null; then
			echo "clang-format: $f is not formatted:"
			diff -u "$f" <("$CLANG_FORMAT" "$f") || true
			status=1
		fi
	done
	exit $status
fi

"$CLANG_FORMAT" -i $FILES
