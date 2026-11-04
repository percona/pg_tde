# pg_tde_rewind and key or provider changes after the divergence
import pytest
from stormweaver.keyrings.file import FileKeyring

from pgtde import api

SERVER_KEY = "global-db-principal-key"


def _db_with_key(node, keyring, db, rows):
    node.safe_sql(f"CREATE DATABASE {db}")
    with node.connect(db=db) as c:
        api.create_extension(c)
        api.add_provider(c, keyring, f"{db}-provider")
        api.create_key(c, f"{db}-key", f"{db}-provider")
        api.set_key(c, f"{db}-key", f"{db}-provider")
        c.safe_sql(f"CREATE TABLE {db}_t (id int) USING tde_heap; INSERT INTO {db}_t SELECT generate_series(1, {rows})")


def _db_state(node, db):
    with node.connect(db=db) as c:
        rows = c.sql_value(f"SELECT count(*) FROM {db}_t")
        encrypted = c.sql_value(f"SELECT pg_tde_is_encrypted('{db}_t')")
        return rows, api.key_info(c)[2], encrypted


# The new primary rotates its principal key five times and its server key
# once; the rewound node ends up with the source's keys and reads data
# written under each of them.
@pytest.mark.parametrize("mode", ["local", "remote"])
def test_rewind_after_source_key_rotation(mode, file_rewind_driver):
    with file_rewind_driver() as rw:
        p = rw.setup_primary()
        p.safe_sql("CREATE TABLE rot_t (id int); INSERT INTO rot_t SELECT generate_series(1, 100)")
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        rw.promote_standby()
        for i in range(5):
            api.create_key(s, f"source-key-{i}", "db-provider")
            api.set_key(s, f"source-key-{i}", "db-provider")
            s.safe_sql(f"INSERT INTO rot_t VALUES ({1000 + i})")
            s.safe_sql("CHECKPOINT")
        api.create_key(s, "source-server-key", "wal-provider", scope="global")
        api.set_server_key(s, "source-server-key", "wal-provider")
        s.safe_sql("CREATE TABLE after_rot (id int); INSERT INTO after_rot VALUES (1)")
        p.safe_sql("INSERT INTO rot_t VALUES (888888)")

        rw.run_rewind(mode)

        assert api.key_info(p)[1:] == ["db-provider", "source-key-4"]
        assert api.server_key_info(p)[1:] == ["wal-provider", "source-server-key"]
        assert p.sql_value("SELECT count(*) FROM rot_t") == "105"
        assert p.sql_value("SELECT count(*) FROM after_rot") == "1"
        assert p.is_encrypted("after_rot")
        assert p.sql_value("SHOW pg_tde.wal_encrypt") == "on"


# A key rotation on the old primary after the divergence is thrown away.
def test_rewind_discards_target_key_rotation(file_rewind_driver):
    with file_rewind_driver() as rw:
        p = rw.setup_primary()
        p.safe_sql("CREATE TABLE orphan_t (id int); INSERT INTO orphan_t SELECT generate_series(1, 100)")
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        rw.promote_standby()
        s.safe_sql("INSERT INTO orphan_t SELECT generate_series(101, 200)")
        api.create_key(p, "orphaned-key", "db-provider")
        api.set_key(p, "orphaned-key", "db-provider")
        api.create_key(p, "orphaned-server-key", "wal-provider", scope="global")
        api.set_server_key(p, "orphaned-server-key", "wal-provider")
        p.safe_sql("INSERT INTO orphan_t SELECT generate_series(901, 999)")
        p.safe_sql("CREATE TABLE orphan_new (id int); INSERT INTO orphan_new VALUES (1)")

        rw.run_rewind("local")

        assert api.key_info(p)[2] == "test-db-key"
        assert api.server_key_info(p)[2] == SERVER_KEY
        assert p.sql_value("SELECT count(*) FROM orphan_t") == "200"
        assert p.sql_value("SELECT to_regclass('orphan_new')") is None


# The new primary adds a global provider on another key file and moves both
# its server key and its principal key there.
def test_rewind_new_provider_on_source(file_rewind_driver, tmp_path):
    with file_rewind_driver() as rw:
        p = rw.setup_primary()
        p.safe_sql("CREATE TABLE prov_t (id int); INSERT INTO prov_t VALUES (1)")
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        rw.promote_standby()
        api.add_provider(s, FileKeyring(tmp_path / "second.keys"), "provider-2", scope="global")
        api.create_key(s, "key-2", "provider-2", scope="global")
        api.set_server_key(s, "key-2", "provider-2")
        api.set_key(s, "key-2", "provider-2", scope="global")
        s.safe_sql("INSERT INTO prov_t VALUES (2)")
        s.safe_sql("CREATE TABLE prov_new (id int); INSERT INTO prov_new VALUES (1)")
        p.safe_sql("INSERT INTO prov_t VALUES (99)")

        rw.run_rewind("local")

        assert api.key_info(p)[1:] == ["provider-2", "key-2"]
        assert api.server_key_info(p)[1:] == ["provider-2", "key-2"]
        assert p.sql_value("SELECT string_agg(id::text, ',' ORDER BY id) FROM prov_t") == "1,2"
        assert p.sql_value("SELECT count(*) FROM prov_new") == "1"
        assert p.is_encrypted("prov_new")


# The old primary drops pg_tde with its tables and sets it up again with
# other providers and keys; the rewind brings the source's state back.
def test_rewind_discards_recreated_extension(file_rewind_driver, tmp_path):
    with file_rewind_driver() as rw:
        p = rw.setup_primary()
        p.safe_sql("CREATE TABLE ext_t (id int); INSERT INTO ext_t SELECT generate_series(1, 100)")
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        rw.promote_standby()
        s.safe_sql("INSERT INTO ext_t SELECT generate_series(101, 200)")
        rogue = FileKeyring(tmp_path / "rogue.keys")
        api.drop_extension(p, cascade=True)
        api.create_extension(p)
        api.add_provider(p, rogue, "rogue-provider")
        api.create_key(p, "rogue-key", "rogue-provider")
        api.set_key(p, "rogue-key", "rogue-provider")
        api.add_provider(p, rogue, "rogue-global", scope="global")
        api.create_key(p, "rogue-server-key", "rogue-global", scope="global")
        api.set_server_key(p, "rogue-server-key", "rogue-global")
        p.safe_sql("CREATE TABLE rogue_t (id int); INSERT INTO rogue_t VALUES (999)")

        rw.run_rewind("local")

        assert p.sql_value("SELECT to_regclass('rogue_t')") is None
        assert p.sql_value("SELECT count(*) FROM ext_t") == "200"
        assert [r[1] for r in api.list_providers(p)] == ["db-provider"]
        assert [r[1] for r in api.list_providers(p, scope="global")] == ["wal-provider"]
        assert api.key_info(p)[1:] == ["db-provider", "test-db-key"]
        assert api.server_key_info(p)[2] == SERVER_KEY


# Databases with their own providers and keys: one kept, one dropped on the
# new primary, one created on each side after the divergence.
def test_rewind_keeps_database_keys(file_rewind_driver):
    with file_rewind_driver() as rw:
        p = rw.setup_primary()
        _db_with_key(p, rw.keyring, "kept", 50)
        _db_with_key(p, rw.keyring, "doomed", 3)
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        rw.promote_standby()
        s.safe_sql("DROP DATABASE doomed")
        _db_with_key(s, rw.keyring, "fresh", 7)
        with s.connect(db="kept") as c:
            c.safe_sql("INSERT INTO kept_t VALUES (51)")
        with p.connect(db="doomed") as c:
            c.safe_sql("INSERT INTO doomed_t VALUES (99)")
        _db_with_key(p, rw.keyring, "orphan", 5)

        rw.run_rewind("local")

        assert [r[0] for r in p.safe_sql("SELECT datname FROM pg_database ORDER BY 1")] == [
            "fresh",
            "kept",
            "postgres",
            "template0",
            "template1",
        ]
        assert _db_state(p, "kept") == ("51", "kept-key", "t")
        assert _db_state(p, "fresh") == ("7", "fresh-key", "t")


# Without its key file the rewound node refuses to start, it does not run on
# guessed keys; once the file is back it starts and follows again.
def test_rewound_node_needs_key_file(file_rewind_driver, file_keyring):
    with file_rewind_driver() as rw:
        p = rw.setup_primary()
        p.safe_sql("CREATE TABLE removable_t (id int); INSERT INTO removable_t VALUES (1)")
        p.safe_sql("CHECKPOINT")
        s = rw.create_standby()
        rw.promote_standby()
        s.safe_sql("INSERT INTO removable_t VALUES (2)")

        rw.run_rewind("local")

        p.stop()
        moved = file_keyring.path.with_name("moved.keys")
        file_keyring.path.rename(moved)
        offset = p.log_offset()
        with pytest.raises(RuntimeError, match="server did not become ready"):
            p.start()
        assert f'FATAL:  key "{SERVER_KEY}" not found in key provider "wal-provider"' in p.log_since(offset)
        # reaps the failed start
        p.stop()

        moved.rename(file_keyring.path)
        p.start()
        s.safe_sql("INSERT INTO removable_t VALUES (3)")
        s.wait_for_catchup(p)
        assert p.sql_value("SELECT string_agg(id::text, ',' ORDER BY id) FROM removable_t") == "1,2,3"
