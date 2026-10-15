#!/bin/bash

set -e

# Installs what pg_tde's CI jobs need on Ubuntu. With "format" as the argument
# it also installs clang-format, which only the format check uses.

# Only needed to build PostgreSQL itself, which the prebuilt CI images
# (percona-lab/pg_github_actions_images, which set PG_INSTALL_DIR) already did.
PG_DEPS=(
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
)

DEPS=(
    wget
    # pg_tde dependencies
    cmake
    meson
    # pg_tde test dependencies
    libjson-xs-perl
    lcov
    perltidy
)

if [ -z "${PG_INSTALL_DIR:-}" ]; then
    DEPS+=("${PG_DEPS[@]}")
fi

if [ "$1" = format ]; then
    # What apt.llvm.org's llvm.sh needs
    DEPS+=(gnupg lsb-release software-properties-common)
fi

# The images carry most of these, so skip apt when there is nothing to install.
if ! dpkg -s "${DEPS[@]}" >/dev/null 2>&1; then
    sudo apt-get update
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${DEPS[@]}"
fi

# t/keys_update.pl starts from a data directory initdb'd with en_US.UTF-8, which
# GitHub-hosted runners have but containers might not.
if ! locale -a | grep -qx en_US.utf8; then
    sudo locale-gen en_US.UTF-8
fi

# Everything below is pg_tde-specific and downloaded from third-party hosts, so
# the shared CI images do not carry it: jobs running in them install it here.
# Skip whatever is already present, so a second run, or an environment that has
# it, costs nothing.

if [ "$1" = format ] && ! command -v clang-format-22 >/dev/null; then
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
