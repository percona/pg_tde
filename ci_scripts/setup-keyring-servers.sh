#!/bin/bash

set -e

SCRIPT_DIR="$(cd -- "$(dirname "$0")" >/dev/null 2>&1; pwd -P)"

cd /tmp

wget https://raw.githubusercontent.com/OpenKMIP/PyKMIP/refs/heads/master/bin/create_certificates.py
python3 create_certificates.py

mkdir policies
cd policies
wget https://raw.githubusercontent.com/OpenKMIP/PyKMIP/refs/heads/master/examples/policy.json
cd ..

echo $SCRIPT_DIR
rm -f /tmp/pykmip.db
pykmip-server -f "$SCRIPT_DIR/../pykmip-server.conf" -l /tmp/kmip-server.log &
