import pytest

from pgtde import api
from pgtde.node import TdeNode
from pgtde.upgrade import update_extension
from pgtde.upgrade_data import RICH_CONFIG, build_rich, check_rich, encrypted_old, exercise_rich, t_enc_rows
from pgtde.wal import wal_contains

pytestmark = pytest.mark.old_install(same_major=True)


def _on_new_binary(upgrade, node):
    assert api.version(node).startswith(f"pg_tde {upgrade.suite_tde}.")
    # the catalog keeps the old version until ALTER EXTENSION UPDATE
    assert api.tde_version(node) == upgrade.old_tde


def test_in_place_start_keeps_encrypted_data(upgrade, tde_node_factory, keyring_obj):
    node = encrypted_old(upgrade, tde_node_factory, keyring_obj, "inplace", wal_encrypt=True)
    assert api.tde_version(node) == upgrade.old_tde
    upgrade.restart_on_new(node)
    _on_new_binary(upgrade, node)
    assert t_enc_rows(node) == "100"
    update_extension(node)
    update_extension(node)
    assert api.tde_version(node) == upgrade.suite_tde
    assert t_enc_rows(node) == "100"
    assert [r[1] for r in api.list_providers(node, scope="global")] == ["global-provider"]
    assert api.server_key_info(node)[1:] == ["global-provider", "server-key"]
    assert api.key_info(node)[1:] == ["global-provider", "db-key"]
    assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
    node.safe_sql("INSERT INTO t_enc SELECT i, md5(i::text) FROM generate_series(101, 200) i")
    node.safe_sql("CREATE TABLE wal_t (v text) USING heap; INSERT INTO wal_t VALUES ('inplace-wal-marker')")
    assert not wal_contains(node, "inplace-wal-marker")
    node.restart()
    assert t_enc_rows(node) == "200"
    assert api.is_encrypted(node, "t_enc") is True


def test_in_place_keeps_rich_schema(upgrade, tde_node_factory, file_keyring, tmp_path):
    node = upgrade.old_node(tde_node_factory, "inplace", config=RICH_CONFIG)
    build_rich(node, file_keyring, tmp_path)
    upgrade.restart_on_new(node)
    _on_new_binary(upgrade, node)
    check_rich(node)
    update_extension(node)
    check_rich(node)
    node.restart()
    check_rich(node)
    exercise_rich(node)


def test_in_place_standby_first(upgrade, tde_node_factory, file_keyring):
    primary = encrypted_old(upgrade, tde_node_factory, file_keyring, "primary", wal_encrypt=True)
    with TdeNode.from_backup(primary.tde_basebackup(), primary, name="standby") as standby:
        for node in (primary, standby):
            assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on", node.name

        # rolling: standby on the new binaries first, still following the old primary
        upgrade.restart_on_new(standby)
        _on_new_binary(upgrade, standby)
        primary.safe_sql("INSERT INTO t_enc SELECT i, md5(i::text) FROM generate_series(101, 150) i")
        primary.safe_sql("CREATE TABLE t_mid (id int) USING tde_heap; INSERT INTO t_mid VALUES (1)")
        primary.wait_for_catchup(standby)
        assert t_enc_rows(standby) == "150"
        assert standby.sql_value("SELECT id FROM t_mid") == "1"

        upgrade.restart_on_new(primary)
        _on_new_binary(upgrade, primary)
        assert t_enc_rows(primary) == "150"
        update_extension(primary)
        primary.safe_sql("INSERT INTO t_enc SELECT i, md5(i::text) FROM generate_series(151, 200) i")
        primary.safe_sql("CREATE TABLE t_post (id int) USING tde_heap; INSERT INTO t_post VALUES (2)")
        primary.wait_for_catchup(standby)
        assert api.tde_version(standby) == upgrade.suite_tde
        for node in (primary, standby):
            assert t_enc_rows(node) == "200", node.name
            assert node.sql_value("SELECT id FROM t_post") == "2", node.name
            assert api.is_encrypted(node, "t_post") is True, node.name
            assert [r[1] for r in api.list_providers(node, scope="global")] == ["global-provider"], node.name
            assert api.key_info(node)[1:] == ["global-provider", "db-key"], node.name
            assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on", node.name
        standby.restart()
        assert t_enc_rows(standby) == "200"
        assert standby.sql_value("SELECT pg_is_in_recovery()") == "t"
