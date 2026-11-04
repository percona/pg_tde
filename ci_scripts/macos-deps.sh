#!/bin/bash

set -e

DEPS=(
    # Setup
    wget
    # Build
    docbook
    docbook-xsl
    fop
    gnu-sed
    icu4c
    libxslt
    lz4
    openssl
    zstd
    # Build pg_tde
    meson
)

brew update
brew install ${DEPS[@]}

# OpenBao
wget https://github.com/openbao/openbao/releases/download/v2.4.3/bao_2.4.3_Darwin_arm64.tar.gz
tar -xzf bao_2.4.3_Darwin_arm64.tar.gz
sudo mv bao /usr/local/bin/bao

if [[ -n $GITHUB_ACTIONS ]]; then
    echo "CPPFLAGS=-I/opt/homebrew/include" >> $GITHUB_ENV
    echo "LDFLAGS=-L/opt/homebrew/lib" >> $GITHUB_ENV
    echo "PKG_CONFIG_PATH=/opt/homebrew/opt/icu4c/lib/pkgconfig" >> $GITHUB_ENV
    echo "XML_CATALOG_FILES=/opt/homebrew/etc/xml/catalog" >> $GITHUB_ENV
fi

# PSP is configured with --enable-tap-tests and test-global-tde.sh runs them
cpan -T IPC::Run
