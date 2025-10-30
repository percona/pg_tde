# Impact of pg_tde on database operations

This page summarizes how `pg_tde` interacts with core PostgreSQL operations.

| Area | Affected | Notes / Actions |
|------|-----------|-----------------|
| **Backups** | ✅ Yes | Encrypted backups require `pg_tde`-aware tools. See [Backup with WAL encryption](../how-to/backup-wal-enabled.md). |
| **Restore** | ✅ Yes | Restored data remains encrypted; `pg_tde` transparently handles decryption. See [Restore encrypted backups](../how-to/restore-backups.md). |
| **Streaming replication** | ⚠️ Partial | Replication requires `pg_tde` on replicas. If keys are local, they must be manually copied; shared KMS works automatically. |
| **Logical replication** | ? | ? |
| **Monitoring and statistics** | ? | how will `pg_stat_monitor` be affected? |
| **Extensions** | ? | ? |
| **Maintenance operations** | ? | ? |
| **Upgrades and migrations** | ? | ? |
| **Performance** | ⚠️ Slight | Minor CPU overhead due to enabling encryption. |
| **Configuration management** | ✅ Yes | `pg_tde.conf` parameters affect key handling and WAL encryption. |
