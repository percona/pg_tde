# Configure PostgreSQL with FIPS Mode (OpenSSL 3.x)

You can activate FIPS mode by inheriting the cryptographic behavior from OpenSSL, so if your OpenSSL is FIPS-validated and runs in FIPS mode, PostgreSQL automatically uses it.

in one of two ways:

## Install Prerequisites

```bash
sudo apt install build-essential perl git wget
# or on RHEL / Rocky:
# sudo dnf groupinstall "Development Tools"
# sudo dnf install perl-core wget git
```

