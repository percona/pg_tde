# FIPS mode and PostgreSQL

# FIPS mode and PostgreSQL

PostgreSQL can operate in environments where OpenSSL is configured in FIPS mode. This ensures compliance with the U.S. **Federal Information Processing Standard (FIPS) 140**.

!!! note
    While PostgreSQL itself is **not** a FIPS-certified cryptographic module, it uses OpenSSL for encryption, hashing, and SSL/TLS operations. Therefore, its behavior depends on the OpenSSL configuration.

## OpenSSL and FIPS mode

FIPS enforcement in PostgreSQL depends entirely on the OpenSSL library version and configuration.

| OpenSSL version | FIPS support | Details |
|:----------------|:-------------|:---------|
| **1.0.2 (legacy)** | ✅ Supported via dedicated “FIPS module.” Used in older RHEL/Fedora releases. |
| **1.1.x (patched)** | ✅ Red Hat backported FIPS support for system-wide enforcement. |
| **3.0+ (modern)** | ✅ Introduces **provider modules** — `default`, `fips`, and `legacy`. The `fips` provider restricts operations to approved algorithms. NIST validation applies only to OpenSSL 3.0, not to later versions (3.1, 3.2). |

### Enabling FIPS mode in OpenSSL

You can activate FIPS mode in one of two ways:

1. **System-wide mode**  
   Enable FIPS at boot time (for example, with RHEL’s `fips=1` kernel parameter).  
   All OpenSSL-based applications, including PostgreSQL, will then use the FIPS provider.

2. **Application-level mode**

   Configure OpenSSL 3.x to load the `fips` provider explicitly.  

   Example configuration:

    ```bash
    openssl_conf = openssl_init
    [openssl_init]
    providers = provider_sect
    [provider_sect]
    fips = fips_sect
    [fips_sect]
    activate = 1
    ```
