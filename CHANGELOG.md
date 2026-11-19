# Changelog

## [Unreleased]

### Added

- Support for PostgreSQL 19 RC 2 ([PG-2536](https://perconadev.atlassian.net/browse/PG-2536), [PG-2813](https://perconadev.atlassian.net/browse/PG-2813))
- Make pg_tde_waldump recognise and print proper data for the pg_tde custom resource manager ([PG-2754](https://perconadev.atlassian.net/browse/PG-2754))

### Fixed

- Escape key names in Vault request URLs, so a key name cannot refer to a path outside the configured mount ([PG-2948](https://perconadev.atlassian.net/browse/PG-2948)
- Report when a Vault request URL is too long instead of silently truncating ti ([PG-2947](https://perconadev.atlassian.net/browse/PG-2947)


## 2.2.2

### Fixed

- Make WAL archive tools work with pg_wal dir as symlink ([PG-2609](https://perconadev.atlassian.net/browse/PG-2609))
- ...
