#!/bin/bash

set -e

if [ "$1" = format ]; then
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y software-properties-common
    sudo DEBIAN_FRONTEND=noninteractive bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)" -- 22
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y clang-format-22
fi

ARCH=$(dpkg --print-architecture)

# Cosmian KMS
COSMIAN_VERSION=5.21.0
wget -O /tmp/cosmian-kms.deb https://package.cosmian.com/kms/$COSMIAN_VERSION/deb/$ARCH/non-fips/static/cosmian-kms-server-non-fips-static-openssl_${COSMIAN_VERSION}_$ARCH.deb
sudo DEBIAN_FRONTEND=noninteractive dpkg -i /tmp/cosmian-kms.deb
# .deb ships binary + bundled legacy.so as 0500 root:root; CI runner is non-root.
sudo chmod 0755 /usr/sbin/cosmian_kms
sudo chmod 0755 /usr/local/cosmian/lib/ossl-modules/legacy.so

# OpenBao
OPENBAO_VERSION=2.5.4
wget -O /tmp/openbao.deb https://github.com/openbao/openbao/releases/download/v$OPENBAO_VERSION/openbao_${OPENBAO_VERSION}_linux_$ARCH.deb
sudo DEBIAN_FRONTEND=noninteractive dpkg -i /tmp/openbao.deb
