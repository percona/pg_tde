import shutil
import tempfile
from pathlib import Path

import pytest
import stormweaver.testing as st
from stormweaver.backends.postgres import Postgres

from pgtde.node import TdeNode
from pgtde.standby import standby_from_backup_dir

# tmpfs mount point for temporary files is Linux specific
pytestmark = pytest.mark.linux_only


def test_wal_archiving_symlink(pg_install, sw_log_dir, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    wal_dir = tmp_path / "pg_wal"
    decrypt = pg_install.bindir / "pg_tde_archive_decrypt"
    restore = pg_install.bindir / "pg_tde_restore_encrypt"

    base = Path(tempfile.mkdtemp(prefix="sw-primary-", dir="/tmp"))
    pg = Postgres(pg_install.install_dir, base / "primary", port=st.alloc_port())
    pg.add_config(
        {
            "shared_preload_libraries": "pg_tde",
            "wal_level": "replica",
            "autovacuum": "off",
            "checkpoint_timeout": "1h",
            "archive_mode": "on",
            "archive_command": f'{decrypt} %f %p "cp %%p {archive}/%%f"',
        }
    )
    primary = TdeNode(pg, "postgres", "primary")
    primary._owned_dir = base

    with primary:
        shutil.move(primary.datadir / "pg_wal", wal_dir)
        (primary.datadir / "pg_wal").symlink_to(wal_dir)

        log_offset = primary.log_offset()
        primary.start()
        primary.setup_server_key(tmp_path / "global.keys", provider="keyring", key="server-key")
        primary.db.add_config({"pg_tde.wal_encrypt": "on"})
        primary.restart()

        # -X none: no WAL in the backup, it must come from the archive
        backup = primary.basebackup(extra_args=["-X", "none"])

        primary.safe_sql("CREATE TABLE t1 AS SELECT 'foobar' AS x")
        primary.stop()

        with open(primary.server_log, errors="replace") as f:
            f.seek(log_offset)
            log = f.read()
        assert "pg_tde_archive_decrypt" not in log, "verify there are no pg_tde_archive_decrypt messages in log"

    with standby_from_backup_dir(
        backup,
        pg_install.install_dir,
        name="replica",
        config={"restore_command": f'{restore} %f %p "cp {archive}/%%f %%p"', "archive_mode": "off"},
    ) as replica:
        log_offset = replica.log_offset()
        replica.start()
        replica.wait_for_log("waiting for WAL to become available", log_offset)
        replica.promote()
        assert replica.safe_sql("SELECT * FROM t1") == [["foobar"]], "data is readable after restore"
