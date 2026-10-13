# pg_tde_rewind re-encrypts FSM/VM fork blocks so the server does not zero
# them out on startup.
import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import ALL_MODES, TdeRewindDriver


@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_pg_rewind_enc_fsm(mode, cipher, pg_install_dir, sw_log_dir, tmp_path):
    kr = FileKeyring(tmp_path / "kr.per")
    with TdeRewindDriver(pg_install_dir, cipher=cipher, keyring=kr, debug=True) as rw:
        p = rw.setup_primary()
        log_start = p.log_offset()
        s = rw.create_standby()

        p.safe_sql("CREATE TABLE tbl1 (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap")
        p.safe_sql("INSERT INTO tbl1 (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)")
        p.safe_sql("CHECKPOINT")

        rw.promote_standby()

        s.safe_sql("DELETE FROM tbl1 WHERE id % 15 = 0")
        s.safe_sql("INSERT INTO tbl1 (f1) SELECT repeat('ghijk', 100) FROM generate_series(1, 1000)")

        rw.run_rewind(mode)

        with open(p.server_log, errors="replace") as f:
            f.seek(log_start)
            assert "; zeroing out page" not in f.read()
        assert p.sql_value("SELECT count(*) FROM tbl1") == "1934"
