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
    libipc-run-perl
    # Test pg_tde

    # Run pgperltidy
    perltidy
)

brew update
brew install -y ${DEPS[@]}

sudo bash -c "$(wget -O - https://apt.llvm.org/llvm.sh)"
pip3 install meson pykmip cryptography setuptools wheel

# OpenBao
wget https://github.com/openbao/openbao/releases/download/v2.4.3/bao_2.4.3_Darwin_x86_64.tar.gz 
tar -xzf bao_2.4.3_Darwin_x86_64.tar.gz
sudo mv bao_2.4.3_Darwin_x86_64/bao /usr/local/bin/bao