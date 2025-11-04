# Impact of pg_tde on database operations

This page summarizes how `pg_tde` interacts with core PostgreSQL operations.

| Area | Affected | Notes / Actions |
|------|-----------|-----------------|
| **Backups** | ❌ Yes | Encrypted backups require `pg_tde`-aware tools. See [Backup with WAL encryption](../how-to/backup-wal-enabled.md). |
| **Restore** | ❌ Yes | Restored data remains encrypted; `pg_tde` transparently handles decryption. See [Restore encrypted backups](../how-to/restore-backups.md). |
| **Streaming replication** | ⚠️ Partial | Replication requires `pg_tde` on replicas. |
| **Logical replication** | ✅ No | Not affected. |
| **Monitoring and statistics** | ✅ No | Not affected, including `pg_stat_monitor`. |
| **Performance** | ⚠️ Slight | Minor CPU overhead due to enabling encryption, most noticeable on random write workloads. |
| **Configuration management** | ❌ Yes | `pg_tde.conf` parameters affect key handling and WAL encryption. |
