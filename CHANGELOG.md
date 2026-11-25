## [Unreleased]

### Changed

- The file key provider no longer treats principal key names as if they were case insensitive

### Fixed

- File key provider now reports file access errors instead of a missing key or a corrupted file
- Key creation now errors out on corrupted data files instead of silently creating an unusable key
- Hardened pg_tde_change_key_provider against long JSON input
- Fix bugs where subtransactions and nested statements could result in plaintext tables marked tde_heap ([PG-2946](https://perconadev.atlassian.net/browse/PG-2946))
- Fix pg_tde_basebackup writing unreadable WAL at the start of a segment when encrypting streamed WAL ([PG-2963](https://perconadev.atlassian.net/browse/PG-2963))
- Fix ATTACH PARTITION creating unencrypted indexes on encrypted partitions ([PG-2962](https://perconadev.atlassian.net/browse/PG-2962))

## 2.3.0

### Added

- Support for PostgreSQL 19 ([PG-2536](https://perconadev.atlassian.net/browse/PG-2536), [PG-2813](https://perconadev.atlassian.net/browse/PG-2813))
- Make pg_tde_waldump recognise and print proper data for the pg_tde custom resource manager ([PG-2754](https://perconadev.atlassian.net/browse/PG-2754))

### Fixed

- Key creation now fails if checking the key provider for an existing key fails, instead of storing the key anyway

## 2.2.2

### Fixed

- Make WAL archive tools work with pg_wal dir as symlink ([PG-2609](https://perconadev.atlassian.net/browse/PG-2609))
- ...
