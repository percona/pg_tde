#!/bin/bash

set -e

DEPS=(
    # PostgreeSQL build dependencies
    #
    # Based on https://salsa.debian.org/postgresql/postgresql/-/blob/18/debian/control
    bison
    docbook-xml
    docbook-xsl
    flex
    gettext
    libcurl4-openssl-dev
    libicu-dev
    libipc-run-perl
    libkrb5-dev
    libldap2-dev
    liblz4-dev
    libnuma-dev
    libpam0g-dev
    libperl-dev
    libreadline-dev
    libselinux1-dev
    libssl-dev
    libsystemd-dev
    liburing-dev
    libxml2-dev
    libxml2-utils
    libxslt1-dev
    libzstd-dev
    lz4
    mawk
    perl
    pkgconf
    python3-dev
    systemtap-sdt-dev
    tcl-dev
    uuid-dev
    xsltproc
    zlib1g-dev
    zstd
    # pg_tde dependencies
    meson
    # pg_tde test dependencies
    lcov
    perltidy
)

sudo apt-get update
sudo apt-get install -y ${DEPS[@]}

sudo bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)"

# Cosmian KMS
COSMIAN_VERSION=5.21.0
wget https://package.cosmian.com/kms/$COSMIAN_VERSION/deb/$(dpkg --print-architecture)/non-fips/static/cosmian-kms-server-non-fips-static-openssl_${COSMIAN_VERSION}_$(dpkg --print-architecture).deb
sudo dpkg -i cosmian-kms-server-non-fips-static-openssl_${COSMIAN_VERSION}_$(dpkg --print-architecture).deb
# .deb ships binary + bundled legacy.so as 0500 root:root; CI runner is non-root.
sudo chmod 0755 /usr/sbin/cosmian_kms
sudo chmod 0755 /usr/local/cosmian/lib/ossl-modules/legacy.so

# OpenBao
OPENBAO_VERSION=2.5.4
wget https://github.com/openbao/openbao/releases/download/v$OPENBAO_VERSION/openbao_${OPENBAO_VERSION}_linux_$(dpkg --print-architecture).deb
sudo dpkg -i openbao_${OPENBAO_VERSION}_linux_$(dpkg --print-architecture).deb
