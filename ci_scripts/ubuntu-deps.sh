#!/bin/bash

set -e

if [ "$1" = format ] && ! command -v clang-format-22 >/dev/null; then
    # apt.llvm.org's llvm.sh needs add-apt-repository.
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y software-properties-common
    sudo DEBIAN_FRONTEND=noninteractive bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)" -- 22
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y clang-format-22
fi

ARCH=$(dpkg --print-architecture)
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

# Prints the installed version of package $1, or nothing if it is absent.
installed_version() {
    dpkg-query -W -f='${Status} ${Version}\n' "$1" 2>/dev/null |
        sed -n 's/^install ok installed //p'
}

# Cosmian KMS
COSMIAN_VERSION=5.21.0
if [[ "$(installed_version cosmian-kms-server)" != "$COSMIAN_VERSION"-* ]]; then
    wget -P "$TMP_DIR" https://package.cosmian.com/kms/$COSMIAN_VERSION/deb/$ARCH/non-fips/static/cosmian-kms-server-non-fips-static-openssl_${COSMIAN_VERSION}_$ARCH.deb
    sudo DEBIAN_FRONTEND=noninteractive dpkg -i "$TMP_DIR"/cosmian-kms-server-non-fips-static-openssl_${COSMIAN_VERSION}_$ARCH.deb
    # .deb ships binary + bundled legacy.so as 0500 root:root; CI runner is non-root.
    sudo chmod 0755 /usr/sbin/cosmian_kms
    sudo chmod 0755 /usr/local/cosmian/lib/ossl-modules/legacy.so
fi

# OpenBao
OPENBAO_VERSION=2.5.4
if [[ "$(installed_version openbao)" != "$OPENBAO_VERSION" ]]; then
    wget -P "$TMP_DIR" https://github.com/openbao/openbao/releases/download/v$OPENBAO_VERSION/openbao_${OPENBAO_VERSION}_linux_$ARCH.deb
    sudo DEBIAN_FRONTEND=noninteractive dpkg -i "$TMP_DIR"/openbao_${OPENBAO_VERSION}_linux_$ARCH.deb
fi
