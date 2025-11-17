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

CLUSTER_INFO=$(mktemp)
bao server -dev -dev-tls -dev-cluster-json="$CLUSTER_INFO" > /dev/null &
sleep 10
export VAULT_ROOT_TOKEN_FILE=$(mktemp)
jq -r .root_token "$CLUSTER_INFO" > "$VAULT_ROOT_TOKEN_FILE"
export VAULT_CACERT=$(jq -r .ca_cert_path "$CLUSTER_INFO")
rm "$CLUSTER_INFO"

## We need to enable key/value version 1 engine for just for tests
bao secrets enable -path=kv-v1 -version=1 kv

## Create a test namespace for the tests to test namespace support
bao namespace create pgns
bao secrets enable -ns=pgns -path=secret -description="Production Secrets" kv-v2

if [ -v GITHUB_ACTIONS ]; then
    echo "VAULT_ROOT_TOKEN_FILE=$VAULT_ROOT_TOKEN_FILE" >> $GITHUB_ENV
    echo "VAULT_CACERT=$VAULT_CACERT" >> $GITHUB_ENV
fi
