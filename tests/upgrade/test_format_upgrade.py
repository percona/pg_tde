import tarfile
from pathlib import Path

import pytest

from pgtde import api
from pgtde.node import TdeNode
from pgtde.upgrade import update_extension
from pgtde.upgrade_data import CHURN, check_churn, churn, global_key

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "keys_update_datadir.tar.gz"


# datadir made with pg_tde 2.1.1 on PG18: encrypted WAL, encrypted table, kill -9
@pytest.mark.pg_min(18)
@pytest.mark.pg_max(18)
def test_keys_from_2_1_1(pg_install_dir, sw_log_dir, tmp_path):
    datadir = tmp_path / "keysupdate"
    datadir.mkdir()
    with tarfile.open(FIXTURE) as tar:
        tar.extractall(datadir, filter="data")
    datadir.chmod(0o700)
    (datadir / "postmaster.pid").unlink(missing_ok=True)

    # tcp only, tmp_path can exceed the unix socket path limit
    with TdeNode.adopt(pg_install_dir, datadir, name="keysupdate", unix_socket=False) as node:
        node.start()
        # stderr skipped, collation version mismatch warnings depend on the host
        cp = node.tool("psql", "-X", "-q", "-A", "-t", "-U", "vagrant", "-c", "table test_enc")
        assert cp.returncode == 0, cp.stderr
        assert cp.stdout.strip() == "1\n2"


# pg_tde 2.1 relation key file: 32 byte header, 96 byte entries, entry type at offset 8, 0 = empty
V3_HEADER, V3_ENTRY = 32, 96


def _empty_v3_slots(path):
    data = path.read_bytes()
    assert (len(data) - V3_HEADER) % V3_ENTRY == 0, len(data)
    entries = range(V3_HEADER, len(data), V3_ENTRY)
    return sum(int.from_bytes(data[o + 8 : o + 12], "little") == 0 for o in entries)


def _migrated(node):
    # the relation key files are rewritten on the first start of the new version
    assert (node.datadir / "pg_tde" / "keys_version").exists()


@pytest.mark.bug("PG-2381")
@pytest.mark.parametrize("kind", list(CHURN))
@pytest.mark.old_install(tde_differs=True)
def test_key_migration_skips_empty_entries(upgrade, tde_node_factory, file_keyring, workdir, socketdir, kind):
    old = upgrade.old_node(tde_node_factory, "old")
    global_key(old, file_keyring)
    churn(old, kind)
    check_churn(old, kind)
    dboid = old.sql_value("SELECT oid FROM pg_database WHERE datname = 'postgres'")
    old.stop()
    tde_dir = old.datadir / "pg_tde"
    assert not (tde_dir / "keys_version").exists()
    # the leftovers the migration has to skip
    if kind == "drop_table":
        assert _empty_v3_slots(tde_dir / f"{dboid}_keys") >= 1
    else:
        assert (tde_dir / "0_keys").stat().st_size == 0
    old.start()
    node = upgrade.upgrade_cluster(tde_node_factory, old, socketdir=socketdir, cwd=workdir)
    _migrated(node)
    check_churn(node, kind)
    update_extension(node)
    assert api.tde_version(node) == upgrade.suite_tde
    node.safe_sql("CREATE TABLE t_new (id int) USING tde_heap; INSERT INTO t_new VALUES (1)")
    node.restart()
    check_churn(node, kind)
    assert api.is_encrypted(node, "t_new") is True


DBS = [("postgres", "key-pg", 5), ("db_a", "key-a", 11), ("db_b", "key-b", 17), ("db_shared", "key-pg", 8)]


@pytest.mark.bug("PG-2379")
@pytest.mark.parametrize("postgres_first", [True, False], ids=["postgres-first", "postgres-last"])
@pytest.mark.old_install(tde_differs=True)
def test_key_migration_uses_each_database_key(
    upgrade, tde_node_factory, file_keyring, workdir, socketdir, postgres_first
):
    old = upgrade.old_node(tde_node_factory, "old")
    global_key(old, file_keyring, key="key-pg")
    for db, _, _ in DBS[1:]:
        old.safe_sql(f"CREATE DATABASE {db}")
    old.safe_sql("CREATE DATABASE db_empty")
    for db, key, rows in DBS:
        with old.connect(db=db) as c:
            api.create_extension(c)
            if key != "key-pg":
                api.create_key(c, key, "global-provider", scope="global")
            api.set_key(c, key, "global-provider", scope="global")
            c.safe_sql(
                f"CREATE TABLE enc_t (id int) USING tde_heap; INSERT INTO enc_t SELECT generate_series(1, {rows})"
            )
    # extension and own key, no encrypted relations
    with old.connect(db="db_empty") as c:
        api.create_extension(c)
        api.create_key(c, "key-empty", "global-provider", scope="global")
        api.set_key(c, "key-empty", "global-provider", scope="global")

    node = upgrade.upgrade_cluster(tde_node_factory, old, socketdir=socketdir, cwd=workdir)
    _migrated(node)
    for db, _, rows in DBS:
        with node.connect(db=db) as c:
            assert c.sql_value("SELECT count(*) FROM enc_t") == str(rows), db
    dbs = [db for db, _, _ in DBS] + ["db_empty"]
    for db in dbs if postgres_first else reversed(dbs):
        with node.connect(db=db) as c:
            c.safe_sql("ALTER EXTENSION pg_tde UPDATE")
    node.restart()
    for db, key, rows in DBS:
        with node.connect(db=db) as c:
            assert c.safe_sql("SELECT count(*), sum(id) FROM enc_t") == [[str(rows), str(rows * (rows + 1) // 2)]], db
            assert api.is_encrypted(c, "enc_t") is True, db
            assert api.key_info(c)[1:] == ["global-provider", key], db
            assert api.tde_version(c) == upgrade.suite_tde, db
    with node.connect(db="db_empty") as c:
        assert api.key_info(c)[1:] == ["global-provider", "key-empty"]
        c.safe_sql("CREATE TABLE enc_t (id int) USING tde_heap; INSERT INTO enc_t VALUES (1)")
        assert api.is_encrypted(c, "enc_t") is True
