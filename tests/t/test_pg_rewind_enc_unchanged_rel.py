# The target's keys are preserved for unchanged and kept encrypted relations.
import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import ALL_MODES, TdeRewindDriver


@pytest.mark.parametrize(("mode", "cipher"), ALL_MODES)
def test_pg_rewind_enc_unchanged_rel(mode, cipher, pg_install_dir, sw_log_dir, tmp_path):
    kr = FileKeyring(tmp_path / "kr.per")
    with TdeRewindDriver(pg_install_dir, cipher=cipher, keyring=kr, debug=True) as rw:
        p = rw.setup_primary()
        s = rw.create_standby()

        p.safe_sql("CREATE TABLE tbl (id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY, f1 TEXT) USING tde_heap")
        p.safe_sql("INSERT INTO tbl (f1) SELECT repeat('abcdeF', 1000) FROM generate_series(1, 1000)")
        p.safe_sql("CHECKPOINT")

        rw.promote_standby()

        # leaves the unchanged index files flushed on the source
        s.safe_sql("CHECKPOINT")

        rw.run_rewind(mode)

        assert p.sql_value("SELECT count(*) FROM tbl") == "1000"
