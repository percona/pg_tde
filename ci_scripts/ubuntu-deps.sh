#!/bin/bash

set -e

DEPS=(
    # Setup
    wget
    # Build
    bison
    docbook-xml
    docbook-xsl
    flex
    gettext
    libicu-dev
    libkrb5-dev
    libldap2-dev
    liblz4-dev
    libpam0g-dev
    libperl-dev
    libreadline-dev
    libselinux1-dev
    libssl-dev
    libsystemd-dev
    libxml2-dev
    libxml2-utils
    libxslt1-dev
    libzstd-dev
    lz4
    mawk
    perl
    pkgconf
    systemtap-sdt-dev
    tcl-dev
    uuid-dev
    xsltproc
    zlib1g-dev
    zstd
    # Build pg_tde
    libcurl4-openssl-dev
    # Test
    libipc-run-perl
    # Test pg_tde
    libhttp-server-simple-perl
    lcov
    # Run pgperltidy
    perltidy
)

sudo apt-get update
sudo apt-get install -y ${DEPS[@]}

sudo bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)"
pip3 install meson pykmip cryptography setuptools wheel

# OpenBao
wget https://github.com/openbao/openbao/releases/download/v2.4.3/bao_2.4.3_linux_amd64.deb
sudo dpkg -i bao_2.4.3_linux_amd64.deb
