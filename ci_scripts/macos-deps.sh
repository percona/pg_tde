#!/bin/bash

set -e

DEPS=(
    # Setup
    wget
    # Build
    gnu-sed
    openssl
    icu4c
    lz4
    zstd
    # Build pg_tde
    
    # Test
    # Test pg_tde

    # Run pgperltidy
    perltidy
)

brew update
brew install ${DEPS[@]}

pip3 install meson pykmip cryptography setuptools wheel

# OpenBao
wget https://github.com/openbao/openbao/releases/download/v2.4.3/bao_2.4.3_Darwin_arm64.tar.gz 
tar -xzf bao_2.4.3_Darwin_arm64.tar.gz

ls -l 
ls -l bao_2.4.3_Darwin_arm64/
ls -l /usr/local/bin/
sudo mv bao_2.4.3_Darwin_arm64/bao /usr/local/bin/bao