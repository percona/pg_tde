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
wget https://package.cosmian.com/kms/5.21.0/deb/$(dpkg --print-architecture)/non-fips/static/cosmian-kms-server-non-fips-static-openssl_5.21.0_$(dpkg --print-architecture).deb
sudo dpkg -i cosmian-kms-server-non-fips-static-openssl_5.21.0_$(dpkg --print-architecture).deb
# .deb ships binary + bundled legacy.so as 0500 root:root; CI runner is non-root.
sudo chmod 0755 /usr/sbin/cosmian_kms
sudo chmod 0755 /usr/local/cosmian/lib/ossl-modules/legacy.so

# OpenBao
wget https://github.com/openbao/openbao/releases/download/v2.4.3/bao_2.4.3_linux_$(dpkg --print-architecture).deb
sudo dpkg -i bao_2.4.3_linux_$(dpkg --print-architecture).deb
