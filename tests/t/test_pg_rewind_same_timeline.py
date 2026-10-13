# pg_tde_rewind with source and target on the same timeline succeeds.
import stormweaver.testing as st
from stormweaver.keyrings.file import FileKeyring

from pgtde.rewind import TdeRewindDriver


def test_pg_rewind_same_timeline(pg_install_dir, sw_log_dir, tmp_path):
    kr = FileKeyring(tmp_path / "kr.per")
    with TdeRewindDriver(pg_install_dir, cipher="aes_128", keyring=kr, debug=True) as rw:
        p = rw.setup_primary()
        s = rw.create_standby()

        # run_rewind("local") minus its catchup wait: the source is no primary
        p.stop(mode="immediate")
        with p.db.preserve_config() as conf:
            s.stop()
            st.command_ok(
                p.run_bin(
                    rw.rewind_bin,
                    "--debug",
                    f"--source-pgdata={s.datadir}",
                    f"--target-pgdata={p.datadir}",
                    "--no-sync",
                    f"--config-file={conf}",
                ),
                "pg_rewind local",
            )
        p.rejoin_as_standby(s)
