import re
import struct

import stormweaver.testing as st

# TLI-LSNh-LSNl.TBLSPCOID.DBOID.NODEOID.BLKNO[_fork]
FILE_RE = re.compile(
    r"^[0-9A-F]{8}-([0-9A-F]{8})-([0-9A-F]{8})[.][0-9]+[.][0-9]+[.][0-9]+[.][0-9]+(?:_vm|_init|_fsm|_main)?$"
)

RELATION_SQL = """
    SELECT format(
        '%s/%s/%s',
        CASE WHEN reltablespace = 0 THEN dattablespace ELSE reltablespace END,
        pg_database.oid,
        pg_relation_filenode(pg_class.oid))
    FROM pg_class, pg_database
    WHERE relname = 'test_table' AND datname = current_database()
"""


def block_lsn(path, blocksize):
    block = path.read_bytes()[:blocksize]
    assert len(block) == blocksize, f"could not read block from {path}"
    hi, lo = struct.unpack("<II", block[:8])
    return f"{hi:08X}", f"{lo:08X}"


def test_pg_waldump_fullpage(tde_node_factory, keyring_obj, tmp_path):
    config = {"wal_level": "replica", "max_wal_senders": "4"}
    node = tde_node_factory("main", config=config)
    node.setup_server_key(keyring_obj, provider="file-keyring-wal", key="server-key")
    node.db.add_config({"pg_tde.wal_encrypt": "on"})
    node.restart()

    # data/WAL with full pages in it
    node.safe_sql("SELECT 'init' FROM pg_create_physical_replication_slot('regress_pg_waldump_slot', true, false)")
    node.safe_sql("CREATE TABLE test_table AS SELECT generate_series(1,100) a")
    # force FPWs on the next writes
    node.safe_sql("CHECKPOINT")
    node.safe_sql("UPDATE test_table SET a = a + 1")

    [[walfile_name, blocksize]] = node.safe_sql(
        "SELECT pg_walfile_name(pg_switch_wal()), current_setting('block_size')"
    )
    relation = node.sql_value(RELATION_SQL)

    walfile = node.datadir / "pg_wal" / walfile_name
    assert walfile.is_file(), "Got a WAL file"

    raw = tmp_path / "raw"
    st.command_ok(
        node.tool(
            "pg_tde_waldump",
            "--quiet",
            "-k",
            node.datadir / "pg_tde",
            "--save-fullpage",
            raw,
            "--relation",
            relation,
            walfile,
        ),
        "pg_waldump with --save-fullpage runs",
    )

    file_count = 0
    for path in sorted(raw.glob("*")):
        m = FILE_RE.search(path.name)
        assert m, f"verify filename format for file {path.name}"
        file_count += 1
        hi_bk, lo_bk = block_lsn(path, int(blocksize))
        # the LSN on the block comes before the file's LSN
        assert m.group(1) + m.group(2) > hi_bk + lo_bk, "LSN stored in the file precedes the one stored in the block"

    assert file_count > 0, "verify that at least one block has been saved"
