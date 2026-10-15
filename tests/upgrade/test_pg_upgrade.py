import hashlib
import re
from pathlib import Path

import pytest
import stormweaver.testing as st

from pgtde import api
from pgtde.checks import setup_error
from pgtde.standby import standby_from_backup_dir
from pgtde.upgrade import update_extension
from pgtde.upgrade_data import (
    RICH_CONFIG,
    build_rich,
    check_rich,
    encrypted_old,
    exercise_rich,
    global_key,
    t_enc_rows,
)
from pgtde.wal import archive_all, archive_config, restore_command, wal_contains


def _upgrade(node, old, new, socketdir, cwd):
    bindir = Path(node.db.install_dir) / "bin"
    return node.tool(
        "pg_tde_upgrade",
        "--no-sync",
        "--old-datadir",
        old.datadir,
        "--new-datadir",
        new.datadir,
        "--old-bindir",
        bindir,
        "--new-bindir",
        bindir,
        "--socketdir",
        socketdir,
        "--old-port",
        str(old.port),
        "--new-port",
        str(new.port),
        cwd=cwd,
    )


def test_pg_tde_upgrade(tde_node_factory, file_keyring, tools, workdir, socketdir):
    tools.help_ok("pg_tde_upgrade")
    tools.version_ok("pg_tde_upgrade")
    tools.options_ok("pg_tde_upgrade")

    oldnotde = tde_node_factory("oldnotde", preload="")
    newnotde = tde_node_factory("newnotde", start=False, preload="")
    oldnotde.safe_sql("CREATE TABLE test_plain (k int, PRIMARY KEY (k))")
    oldnotde.safe_sql("INSERT INTO test_plain (k) VALUES (1), (2)")
    oldnotde.stop()

    st.command_ok(
        _upgrade(newnotde, oldnotde, newnotde, socketdir, workdir),
        "executes pg_upgrade successfully without pg_tde",
    )

    newnotde.start()
    assert newnotde.safe_sql("SELECT * FROM test_plain") == [["1"], ["2"]]
    newnotde.stop()

    old = tde_node_factory("old")
    new = tde_node_factory("new", start=False, config={"pg_tde.wal_encrypt": "on"})
    old.setup_server_key(file_keyring, provider="file-vault", key="server-key")
    api.set_key(old, "server-key", "file-vault", scope="global")
    api.set_wal_encrypt(old, True)
    old.safe_sql("CREATE TABLE test_enc (k int, PRIMARY KEY (k)) USING tde_heap")
    old.safe_sql("INSERT INTO test_enc (k) VALUES (1), (2)")
    old.restart()
    old.stop()

    st.command_ok(_upgrade(new, old, new, socketdir, workdir), "executes pg_upgrade successfully with pg_tde")

    new.start()
    assert new.safe_sql("SELECT * FROM test_enc") == [["1"], ["2"]]
    new.stop()


def _pg_tde_upgrade(upgrade, tde_node_factory, old, socketdir, workdir, *extra, **new_kw):
    new = upgrade.new_node(tde_node_factory, "new", old, **new_kw)
    st.command_ok(upgrade.run_pg_tde_upgrade(old, new, *extra, socketdir=socketdir, cwd=workdir), "pg_tde_upgrade")
    return new


def _check_t_enc(node):
    assert t_enc_rows(node) == "100"
    assert api.is_encrypted(node, "t_enc") is True


@pytest.mark.bug("PG-2240")
@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_keeps_encrypted_data(upgrade, tde_node_factory, keyring_obj, workdir, socketdir):
    old = encrypted_old(upgrade, tde_node_factory, keyring_obj)
    new = _pg_tde_upgrade(upgrade, tde_node_factory, old, socketdir, workdir)
    new.start()
    # catalog keeps the old extension version until ALTER EXTENSION UPDATE
    assert api.tde_version(new) == upgrade.old_tde
    _check_t_enc(new)
    update_extension(new)
    update_extension(new)
    assert api.tde_version(new) == upgrade.suite_tde
    _check_t_enc(new)
    assert [r[1] for r in api.list_providers(new, scope="global")] == ["global-provider"]
    assert api.key_info(new)[1:] == ["global-provider", "db-key"]
    new.safe_sql("CREATE TABLE t_new (id int) USING tde_heap; INSERT INTO t_new VALUES (1)")
    assert api.is_encrypted(new, "t_new") is True
    new.restart()
    _check_t_enc(new)
    new.assert_not_on_disk("t_enc", hashlib.md5(b"50").hexdigest())


@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_keeps_rich_schema(upgrade, tde_node_factory, file_keyring, tmp_path, workdir, socketdir):
    old = upgrade.old_node(tde_node_factory, "old", config=RICH_CONFIG)
    build_rich(old, file_keyring, tmp_path)
    new = _pg_tde_upgrade(upgrade, tde_node_factory, old, socketdir, workdir, config=RICH_CONFIG)
    new.start()
    update_extension(new)
    check_rich(new)
    new.restart()
    check_rich(new)
    exercise_rich(new)


def _wal_marker(node, marker):
    # a heap table: its WAL records carry the row in plaintext unless WAL is encrypted
    node.safe_sql(f"CREATE TABLE IF NOT EXISTS wal_t (v text) USING heap; INSERT INTO wal_t VALUES ('{marker}')")
    return wal_contains(node, marker)


@pytest.mark.parametrize(
    ("old_wal", "new_wal"),
    [
        pytest.param("off", "off", id="off-off"),
        pytest.param("disabled", "off", id="disabled-off"),
        pytest.param("disabled", "after", id="disabled-reenabled"),
        pytest.param("on", "off", id="on-off"),
        pytest.param("on", "before", id="on-on"),
    ],
)
@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_wal_encryption(upgrade, tde_node_factory, file_keyring, workdir, socketdir, old_wal, new_wal):
    old = encrypted_old(upgrade, tde_node_factory, file_keyring)
    if old_wal != "off":
        api.set_wal_encrypt(old, True)
        old.restart()
        assert old.sql_value("SHOW pg_tde.wal_encrypt") == "on"
        assert not _wal_marker(old, "old-wal-marker")
        if old_wal == "disabled":
            api.set_wal_encrypt(old, False)
            old.restart()
    # the new cluster's setting is what counts, the old auto.conf is not carried over
    config = {"pg_tde.wal_encrypt": "on"} if new_wal == "before" else {}
    new = _pg_tde_upgrade(upgrade, tde_node_factory, old, socketdir, workdir, config=config)
    new.start()
    update_extension(new)
    _check_t_enc(new)
    if new_wal == "after":
        api.set_wal_encrypt(new, True)
        new.restart()
    on = new_wal != "off"
    assert new.sql_value("SHOW pg_tde.wal_encrypt") == ("on" if on else "off")
    assert _wal_marker(new, "new-wal-marker") is not on
    new.restart()
    _check_t_enc(new)


@pytest.mark.parametrize("wal_encrypt", [False, True], ids=["wal-plain", "wal-encrypted"])
@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_check(upgrade, tde_node_factory, file_keyring, workdir, socketdir, wal_encrypt):
    old = encrypted_old(upgrade, tde_node_factory, file_keyring)
    if wal_encrypt:
        api.set_wal_encrypt(old, True)
        old.restart()
    new = upgrade.new_node(tde_node_factory, "new", old)
    cp = upgrade.run_pg_tde_upgrade(old, new, "--check", socketdir=socketdir, cwd=workdir)
    st.command_ok(cp, "pg_tde_upgrade --check")
    assert "Clusters are compatible" in cp.stdout
    # the check leaves the old cluster usable and the new one upgradable
    old.start()
    _check_t_enc(old)
    st.command_ok(upgrade.run_pg_tde_upgrade(old, new, socketdir=socketdir, cwd=workdir), "pg_tde_upgrade")
    new.start()
    update_extension(new)
    _check_t_enc(new)


@pytest.mark.parametrize(
    ("args", "transfer"),
    [
        pytest.param(["--link"], "Linking", id="link"),
        pytest.param(["--clone"], "Cloning", id="clone"),
        pytest.param(["--jobs", "4"], "Copying", id="jobs"),
    ],
)
@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_transfer_modes(upgrade, tde_node_factory, file_keyring, workdir, socketdir, args, transfer):
    old = encrypted_old(upgrade, tde_node_factory, file_keyring)
    old.safe_sql(
        "".join(
            f"CREATE TABLE par_{i} (id int) USING tde_heap; INSERT INTO par_{i} SELECT generate_series(1, 100);"
            for i in range(10)
        )
    )
    new = upgrade.new_node(tde_node_factory, "new", old)
    cp = upgrade.run_pg_tde_upgrade(old, new, *args, socketdir=socketdir, cwd=workdir)
    if args == ["--clone"] and cp.returncode != 0:
        m = re.search(r"^.*(could not clone|file cloning not supported).*$", cp.stdout + cp.stderr, re.M | re.I)
        if m:
            pytest.skip(f"--clone refused: {m.group(0).strip()}")
    st.command_ok(cp, f"pg_tde_upgrade {' '.join(args)}")
    assert re.search(rf"^{transfer} user relation files", cp.stdout, re.M | re.I), cp.stdout
    new.start()
    update_extension(new)
    _check_t_enc(new)
    sums = new.sql_value("SELECT " + " + ".join(f"(SELECT sum(id) FROM par_{i})" for i in range(10)))
    assert sums == str(10 * 5050)
    new.assert_not_on_disk("t_enc", hashlib.md5(b"50").hexdigest())


@pytest.mark.parametrize("case", ["running", "unclean", "dirty_target", "wrong_bindir"])
@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_refuses(upgrade, tde_node_factory, file_keyring, workdir, socketdir, case):
    old = encrypted_old(upgrade, tde_node_factory, file_keyring)
    new = upgrade.new_node(tde_node_factory, "new", old)
    kw = {}
    if case == "running":
        kw["stop_old"] = False
        error = r"There seems to be a postmaster servicing the old cluster"
    elif case == "unclean":
        # immediate leaves no pid file, so pg_upgrade does not try crash recovery itself
        old.stop(mode="immediate")
        error = r"The source cluster was not shut down cleanly"
    elif case == "dirty_target":
        new.start()
        new.safe_sql("CREATE TABLE leftover (id int)")
        new.stop()
        error = r'New cluster database "postgres" is not empty'
    else:
        kw["new_bindir"] = upgrade.old.bindir
        error = r"check for \".*\" failed"
    cp = upgrade.run_pg_tde_upgrade(old, new, socketdir=socketdir, cwd=workdir, **kw)
    out = cp.stdout + cp.stderr
    assert cp.returncode != 0, out
    assert re.search(error, out), out
    # the refused run leaves the old cluster intact
    if not old.db.is_running():
        old.start()
    _check_t_enc(old)
    if case == "unclean":
        st.command_ok(upgrade.run_pg_tde_upgrade(old, new, socketdir=socketdir, cwd=workdir), "pg_tde_upgrade")
        new.start()
        update_extension(new)
        _check_t_enc(new)


@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_plain_cluster_then_enable_tde(upgrade, tde_node_factory, file_keyring, workdir, socketdir):
    old = upgrade.old_node(tde_node_factory, "old", preload="")
    old.safe_sql(
        "CREATE TABLE plain_t (id int, v text);"
        "INSERT INTO plain_t SELECT i, md5(i::text) FROM generate_series(1, 200) i"
    )
    new = _pg_tde_upgrade(upgrade, tde_node_factory, old, socketdir, workdir)
    new.start()
    assert new.sql_value("SELECT count(*) FROM plain_t WHERE v = md5(id::text)") == "200"
    global_key(new, file_keyring)
    new.safe_sql("CREATE TABLE t_new (id int) USING tde_heap; INSERT INTO t_new VALUES (1), (2), (3)")
    assert api.is_encrypted(new, "t_new") is True
    assert api.is_encrypted(new, "plain_t") is False
    new.restart()
    assert new.sql_value("SELECT sum(id) FROM t_new") == "6"


@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_after_removing_tde(upgrade, tde_node_factory, file_keyring, workdir, socketdir, request):
    xfail = upgrade.old_tde == "2.1"
    if xfail:
        request.applymarker(pytest.mark.bug("PG-2871"))
        request.applymarker(
            pytest.mark.xfail(
                strict=True,
                raises=AssertionError,
                reason="PG-2871: pg_tde_upgrade from 2.1 fails on wal_keys without pg_tde preloaded",
            )
        )

    def setup():
        old = encrypted_old(upgrade, tde_node_factory, file_keyring)
        old.safe_sql("ALTER TABLE t_enc SET ACCESS METHOD heap")
        api.drop_extension(old)
        return old, upgrade.new_node(tde_node_factory, "new", old, preload="")

    old, new = setup_error(setup)
    cp = upgrade.run_pg_tde_upgrade(old, new, socketdir=socketdir, cwd=workdir)
    if cp.returncode != 0:
        # pg_upgrade keeps the tool output in its log dir
        logs = "".join(p.read_text() for p in new.datadir.glob("pg_upgrade_output.d/*/log/*.log"))
        if re.search(r'WAL key file ".*wal_keys" is corrupted', cp.stdout + cp.stderr + logs):
            raise AssertionError(f"pg_tde_upgrade failed on the copied key files:\n{cp.stdout}")
        raise RuntimeError(f"pg_tde_upgrade failed rc={cp.returncode}:\n{cp.stdout}{cp.stderr}")

    def check():
        new.start()
        assert new.sql_value("SELECT count(*) FROM pg_extension WHERE extname = 'pg_tde'") == "0"
        assert t_enc_rows(new) == "100"
        new.assert_on_disk("t_enc", hashlib.md5(b"50").hexdigest())

    # only the upgrade failure may satisfy the xfail
    if xfail:
        setup_error(check)
    else:
        check()


@pytest.mark.old_install(side_by_side=True)
def test_pg_tde_upgrade_with_enforce_encryption(upgrade, tde_node_factory, file_keyring, workdir, socketdir):
    enforced = r"pg_tde.enforce_encryption is ON, only the tde_heap access method is allowed"
    old = encrypted_old(upgrade, tde_node_factory, file_keyring)
    old.safe_sql("CREATE TABLE legacy_heap (id int) USING heap; INSERT INTO legacy_heap VALUES (1), (2), (3)")
    old.safe_sql("ALTER SYSTEM SET pg_tde.enforce_encryption = on")
    old.restart()
    old.expect_error(enforced, "CREATE TABLE blocked (id int) USING heap")
    # schema restore must keep the heap table heap
    new = _pg_tde_upgrade(
        upgrade, tde_node_factory, old, socketdir, workdir, config={"pg_tde.enforce_encryption": "on"}
    )
    new.start()
    update_extension(new)
    assert new.sql_value("SELECT sum(id) FROM legacy_heap") == "6"
    assert api.is_encrypted(new, "legacy_heap") is False
    _check_t_enc(new)
    new.expect_error(enforced, "CREATE TABLE blocked (id int) USING heap")
    new.safe_sql("CREATE TABLE allowed (id int) USING tde_heap")
    assert api.is_encrypted(new, "allowed") is True


@pytest.mark.old_install(side_by_side=True)
def test_pitr_after_pg_tde_upgrade(upgrade, tde_node_factory, file_keyring, tmp_path, workdir, socketdir):
    archive = tmp_path / "archive"
    archive.mkdir()
    old = encrypted_old(upgrade, tde_node_factory, file_keyring, config=archive_config(upgrade.old.bindir, archive))
    old.safe_sql("CREATE TABLE pitr_t (id int PRIMARY KEY) USING tde_heap; INSERT INTO pitr_t VALUES (1), (2), (3)")
    archive_all(old)
    new = _pg_tde_upgrade(upgrade, tde_node_factory, old, socketdir, workdir)
    new.db.add_config({"pg_tde.wal_encrypt": "on", **archive_config(upgrade.suite.bindir, archive)})
    new.start()
    update_extension(new)
    backup = new.tde_basebackup()
    new.safe_sql("INSERT INTO pitr_t VALUES (4), (5), (6)")
    new.safe_sql("SELECT pg_create_restore_point('before_7')")
    new.safe_sql("INSERT INTO pitr_t VALUES (7), (8)")
    assert not _wal_marker(new, "pitr-wal-marker")
    archive_all(new)
    new.stop()

    config = {
        "archive_mode": "off",
        "restore_command": restore_command(upgrade.suite.bindir, archive),
        "recovery_target_name": "before_7",
        "recovery_target_action": "promote",
    }
    with standby_from_backup_dir(
        backup, upgrade.suite.install_dir, name="pitr", config=config, signal="recovery"
    ) as node:
        node.start()
        node.poll_until("SELECT pg_is_in_recovery()", "f")
        assert re.search(r'restored log file "\w+" from archive', node.log_since(0))
        assert node.safe_sql("SELECT id FROM pitr_t ORDER BY id") == [[str(i)] for i in range(1, 7)]
        assert api.is_encrypted(node, "pitr_t") is True
        _check_t_enc(node)
        assert node.sql_value("SHOW pg_tde.wal_encrypt") == "on"
