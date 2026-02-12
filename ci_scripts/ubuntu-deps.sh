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
    # pg_tde test dependencies
    libhttp-server-simple-perl
    lcov
    perltidy
)

sudo apt-get update
sudo apt-get install -y ${DEPS[@]}

sudo bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)"
pip3 install meson pykmip cryptography setuptools wheel

# OpenBao
wget https://github.com/openbao/openbao/releases/download/v2.4.3/bao_2.4.3_linux_$(dpkg --print-architecture).deb
sudo dpkg -i bao_2.4.3_linux_$(dpkg --print-architecture).deb
