# pg_tde_rewind keeps some WAL segments on the target; restore_command makes
# new WAL keys while the replica is created, so kept segments must be
# re-encrypted.
import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import ALL_MODES, TdeRewindDriver


@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_pg_rewind_enc_keep_wal_seg(mode, cipher, pg_install_dir, sw_log_dir, tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    decrypt = f"{pg_install_dir}/bin/pg_tde_archive_decrypt"
    encrypt = f"{pg_install_dir}/bin/pg_tde_restore_encrypt"
    config = {
        "wal_level": "replica",
        "archive_mode": "on",
        "archive_command": f'{decrypt} %f %p "cp %%p {archive}/%%f"',
        "restore_command": f'{encrypt} %f %p "cp {archive}/%%f %%p"',
    }
    kr = FileKeyring(tmp_path / "kr.per")
    with TdeRewindDriver(pg_install_dir, cipher=cipher, keyring=kr, debug=True, config=config) as rw:
        p = rw.setup_primary()
        p.restart()

        for t in ("tail_t", "block_t"):
            p.safe_sql(
                f"CREATE TABLE {t} (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap"
            )
            p.safe_sql(f"INSERT INTO {t} (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)")
        p.safe_sql("CHECKPOINT")

        s = rw.create_standby()

        rw.promote_standby()

        p.safe_sql("UPDATE block_t SET f1='YYYYYYY' WHERE id % 10 = 0")
        s.safe_sql("INSERT INTO tail_t (f1) SELECT repeat('ghijk', 100) FROM generate_series(1, 1000)")
        s.safe_sql("CHECKPOINT")

        rw.run_rewind(mode)

        assert p.sql_value("SELECT count(*) FROM tail_t") == "2000"
        assert p.sql_value("SELECT count(*) FROM block_t") == "1000"
