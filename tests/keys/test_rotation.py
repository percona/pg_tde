import contextlib
import functools
import time

import pytest
from stormweaver.testing import InjectionPoints
from stormweaver.testing.background import Background

from pgtde.tde import KeyInfo, Provider

# Rotating the principal key of a database re-wraps the relation keys with the new
# principal key. Data stays readable and is not rewritten, the server key is not touched.

ROWS = [(1, 5), (2, 6)]

# provider, scope, provider id as reported by pg_tde_key_info() (global providers are negative)
TARGETS = [
    pytest.param("db-1", "database", 1, id="same_database_provider"),
    pytest.param("db-2", "database", 2, id="other_database_provider"),
    pytest.param("global-1", "global", -1, id="global_provider"),
    pytest.param("global-2", "global", -2, id="second_global_provider"),
]


@pytest.fixture
def provider_keyrings(make_keyring):
    """Provider name -> its own keyring."""
    return {name: make_keyring() for name in ["db-1", "db-2", "global-1", "global-2"]}


@pytest.fixture
def node(tde_node, provider_keyrings, key_name):
    """2 database and 2 global providers, each on its own keyring, a key from db-1, an encrypted table."""
    tde = tde_node.tde
    tde.create_extension()
    tde.add_provider("db-1", provider_keyrings["db-1"])
    tde.add_provider("db-2", provider_keyrings["db-2"])
    tde.add_provider("global-1", provider_keyrings["global-1"], scope="global")
    tde.add_provider("global-2", provider_keyrings["global-2"], scope="global")
    tde.create_key(key_name("initial-key"), "db-1")
    tde.set_key(key_name("initial-key"), "db-1")
    tde_node.execute("CREATE TABLE test_enc (id int PRIMARY KEY, k int) USING tde_heap")
    tde_node.execute("INSERT INTO test_enc VALUES (1, 5), (2, 6)")
    return tde_node


def rotate(node, key, provider, scope="database"):
    node.tde.create_key(key, provider, scope=scope)
    node.tde.set_key(key, provider, scope=scope)


def data(node):
    return node.query("SELECT id, k FROM test_enc ORDER BY id")


def remove_key_file(keyring):
    # vault and kmip providers share one store, nothing to remove per provider
    if keyring.kind == "file":
        keyring.path.unlink()


@pytest.mark.parametrize("provider, scope, provider_id", TARGETS)
def test_rotation_keeps_data_readable(node, key_name, provider, scope, provider_id):
    # nothing but the rotation may touch the relation files between the 2 snapshots
    node.execute("ALTER SYSTEM SET autovacuum = off")
    node.execute("SELECT pg_reload_conf()")
    assert data(node) == ROWS  # also sets the hint bits
    files_before = node.relation_bytes("test_enc")

    rotate(node, key_name("rotated-key"), provider, scope)

    assert node.relation_bytes("test_enc") == files_before, "rotation rewrote relation data"
    node.execute("CREATE TABLE created_after (x int) USING tde_heap")
    node.execute("INSERT INTO created_after VALUES (1)")

    def assert_rotated():
        assert node.tde.key_info() == KeyInfo(provider_id, provider, key_name("rotated-key"))
        assert node.tde.server_key_info() is None
        node.tde.verify_key()
        assert data(node) == ROWS
        assert node.scalar("SELECT x FROM created_after") == 1

    assert_rotated()
    node.restart()
    assert_rotated()


def test_provider_can_be_deleted_after_rotating_away(node, provider_keyrings, key_name):
    node.expect_error(
        "cannot delete provider which is currently in use", "SELECT pg_tde_delete_database_key_provider('db-1')"
    )
    rotate(node, key_name("rotated-key"), "db-1")
    node.expect_error(
        "cannot delete provider which is currently in use", "SELECT pg_tde_delete_database_key_provider('db-1')"
    )

    rotate(node, key_name("rotated-key-2"), "db-2")
    node.tde.delete_provider("db-1")

    assert [p.name for p in node.tde.providers()] == ["db-2"]
    remove_key_file(provider_keyrings["db-1"])
    node.restart()
    assert data(node) == ROWS


# counterpart of the above: the providers really use separate key stores
def test_data_needs_the_key_file_of_the_current_provider(node, provider_keyrings, keyring, key_name):
    if keyring.kind != "file":
        pytest.skip("vault and kmip providers share one store")
    rotate(node, key_name("rotated-key"), "db-2")
    remove_key_file(provider_keyrings["db-2"])
    node.restart()
    node.expect_error(f'key "{key_name("rotated-key")}" not found in key provider "db-2"', "SELECT id, k FROM test_enc")


# several rotations in a row, across providers and scopes, one restart at the end
def test_rotation_chain(node, key_name):
    chain = [("db-2", "database", 2), ("global-1", "global", -1), ("db-1", "database", 1), ("global-2", "global", -2)]
    for i, (provider, scope, provider_id) in enumerate(chain):
        rotate(node, key_name(f"chain-key-{i}"), provider, scope)
        assert node.tde.key_info() == KeyInfo(provider_id, provider, key_name(f"chain-key-{i}"))
        node.execute(f"CREATE TABLE chain_{i} (x int) USING tde_heap")
        node.execute(f"INSERT INTO chain_{i} VALUES ({i})")
        assert data(node) == ROWS

    node.restart()

    assert node.tde.key_info() == KeyInfo(-2, "global-2", key_name("chain-key-3"))
    assert data(node) == ROWS
    for i in range(len(chain)):
        assert node.scalar(f"SELECT x FROM chain_{i}") == i


# pg_tde.inherit_global_providers = off: no new keys from global providers, the current one keeps working
def test_global_providers_can_be_disabled(node, key_name):
    rotate(node, key_name("database-key"), "db-2")
    rotate(node, key_name("global-key"), "global-1", "global")
    current = KeyInfo(-1, "global-1", key_name("global-key"))
    node.execute("ALTER SYSTEM SET pg_tde.inherit_global_providers = off")
    node.restart()

    assert node.tde.key_info() == current
    assert data(node) == ROWS
    node.expect_error(
        "usage of global key providers is disabled",
        f"SELECT pg_tde_create_key_using_global_key_provider('{key_name('another-key')}', 'global-1')",
    )
    node.expect_error(
        "usage of global key providers is disabled",
        f"SELECT pg_tde_set_key_using_global_key_provider('{key_name('global-key')}', 'global-2')",
    )
    assert node.tde.key_info() == current
    assert node.tde.server_key_info() is None

    # back to an existing key, not a new one
    node.tde.set_key(key_name("database-key"), "db-2")
    assert node.tde.key_info() == KeyInfo(2, "db-2", key_name("database-key"))
    assert data(node) == ROWS

    rotate(node, key_name("new-database-key"), "db-1")
    assert node.tde.key_info() == KeyInfo(1, "db-1", key_name("new-database-key"))
    assert data(node) == ROWS


def test_global_provider_named_like_database_provider(node, make_keyring, key_name):
    node.tde.add_provider("db-2", make_keyring(), scope="global")

    rotate(node, key_name("rotated-key"), "db-2", "global")

    def assert_rotated():
        assert node.tde.key_info() == KeyInfo(-3, "db-2", key_name("rotated-key"))
        assert node.tde.server_key_info() is None
        assert data(node) == ROWS

    assert_rotated()
    node.restart()
    assert_rotated()


PROVIDER_TYPE = {"file": "file", "vault": "vault-v2", "kmip": "kmip"}


# not about rotation, moves to test_providers.py when that exists
def test_providers_listing(tde_node, make_keyring):
    tde = tde_node.tde
    tde.create_extension()
    first, second, glob = make_keyring(), make_keyring(), make_keyring()
    tde.add_provider("first", first)
    tde.add_provider("second", second)
    tde.add_provider("global", glob, scope="global")

    providers = tde.providers()
    global_providers = tde.providers(scope="global")
    kind = PROVIDER_TYPE[first.kind]
    if first.kind == "file":
        assert providers == [
            Provider(1, "first", kind, {"path": str(first.path)}),
            Provider(2, "second", kind, {"path": str(second.path)}),
        ]
        assert global_providers == [Provider(-1, "global", kind, {"path": str(glob.path)})]
    else:
        assert [p[:3] for p in providers] == [(1, "first", kind), (2, "second", kind)]
        assert [p[:3] for p in global_providers] == [(-1, "global", kind)]


def test_standby_follows_rotation(node, make_standby, key_name):
    standby = make_standby(node)
    rotate(node, key_name("rotated-key"), "db-2")
    node.execute("CREATE TABLE created_after (x int) USING tde_heap")
    node.execute("INSERT INTO created_after VALUES (1)")
    node.wait_for_catchup(standby)

    def assert_rotated():
        assert standby.tde.key_info() == KeyInfo(2, "db-2", key_name("rotated-key"))
        assert data(standby) == ROWS
        assert standby.scalar("SELECT x FROM created_after") == 1

    assert_rotated()
    standby.restart()
    assert_rotated()

    standby.promote()
    assert standby.tde.key_info() == KeyInfo(2, "db-2", key_name("rotated-key"))
    standby.execute("INSERT INTO test_enc VALUES (3, 7)")
    assert data(standby) == [*ROWS, (3, 7)]
    standby.execute("CREATE TABLE created_after_promote (x int) USING tde_heap")
    standby.execute("INSERT INTO created_after_promote VALUES (2)")
    assert standby.scalar("SELECT x FROM created_after_promote") == 2


def setup_step(f):
    """An AssertionError in f is a broken setup: raise it as RuntimeError, so that a strict
    xfail(raises=AssertionError) does not take it for the expected failure."""

    @functools.wraps(f)
    def step(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except AssertionError as e:
            raise RuntimeError(f"{f.__name__}: {e}") from e

    return step


WALWRITER_FLUSH = "walwriter-before-flush"


def flush_wal(node):
    # the rotation has no xid and its commit does not flush, a commit with one flushes it too
    node.execute("CREATE TABLE flush_wal ()")
    node.execute("DROP TABLE flush_wal")


@pytest.fixture
def parkable_walwriter(tde_node):
    """InjectionPoints when the server can stop the WAL writer before a flush, else None."""
    ip = InjectionPoints(tde_node, poll_db="template1")
    return ip if ip.compiled_in(WALWRITER_FLUSH) and ip.available() else None


@pytest.fixture
def walwriter(parkable_walwriter):
    """parkable_walwriter, skips the test on a server without the point."""
    if parkable_walwriter is None:
        pytest.skip(f"lost rotation WAL record not visible on a server without the {WALWRITER_FLUSH} injection point")
    return parkable_walwriter


def park_walwriter(node, injection_points):
    """Stop the WAL writer before its next flush. A fast shutdown waits for it forever, only a
    kill gets the server down."""
    injection_points.attach(WALWRITER_FLUSH, "wait")
    # an async commit wakes the WAL writer up if it hibernates
    with node.connect() as conn:
        conn.execute("SET synchronous_commit = off")
        conn.execute("CREATE TABLE wake_walwriter ()")
    injection_points.wait_until_reached(WALWRITER_FLUSH)
    walwriter = node.row("SELECT wait_event_type, wait_event FROM pg_stat_activity WHERE backend_type = 'walwriter'")
    assert walwriter == ("InjectionPoint", WALWRITER_FLUSH)


@setup_step
def crash_after_rotation(node, make_standby, key, walwriter, flushed_key=None):
    """Rotate to key on db-2 and crash right after the commit, with a standby attached.

    walwriter: InjectionPoints to park the WAL writer with, None for a server without the point.
    flushed_key: rotate to it first, and flush that rotation to disk.
    """
    # the commit is the only thing that could flush the rotation before the kill, and it does not;
    # keep bgwriter, checkpointer and autovacuum from flushing it by accident
    background_flush = {
        "bgwriter_lru_maxpages": "0",
        "checkpoint_timeout": "1h",
        "autovacuum": "off",
    }
    if walwriter is None:
        # best effort, the WAL writer can still flush before the kill
        background_flush["wal_writer_delay"] = "10s"
    for name, value in background_flush.items():
        node.execute(f"ALTER SYSTEM SET {name} = '{value}'")
    node.restart()
    standby = make_standby(node)

    try:
        if flushed_key is not None:
            rotate(node, flushed_key, "db-2")
            flush_wal(node)
        if walwriter is not None:
            park_walwriter(node, walwriter)
        rotate(node, key, "db-2")
    finally:
        node.kill()
    node.poll_start()
    node.execute("ALTER SYSTEM RESET ALL")
    node.execute("SELECT pg_reload_conf()")
    return standby


def test_rotation_survives_crash(node, make_standby, parkable_walwriter, key_name):
    standby = crash_after_rotation(node, make_standby, key_name("rotated-key"), parkable_walwriter)

    assert_usable(node, KeyInfo(2, "db-2", key_name("rotated-key")))
    node.wait_for_catchup(standby)
    assert data(standby) == ROWS


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="standby stays on the old key: rotation WAL record not flushed at commit, lost",
)
def test_rotation_survives_crash_on_standby(walwriter, node, make_standby, key_name):
    standby = crash_after_rotation(node, make_standby, key_name("rotated-key"), walwriter)

    node.wait_for_catchup(standby)
    assert standby.tde.key_info() == KeyInfo(2, "db-2", key_name("rotated-key"))


# Redo rotates from the key in the map file to the key in the record. The primary replays
# its own, flushed, rotation record onto the map file it already renamed.
def test_rotation_replayed_in_crash_recovery(node, make_standby, key_name):
    rotated = KeyInfo(2, "db-2", key_name("rotated-key"))
    node.execute("ALTER SYSTEM SET checkpoint_timeout = '1h'")
    node.execute("SELECT pg_reload_conf()")
    standby = make_standby(node)
    before_rotation = node.scalar("SELECT pg_current_wal_insert_lsn()")

    rotate(node, rotated.key_name, "db-2")
    flush_wal(node)
    assert node.scalar("SELECT redo_lsn <= $1::pg_lsn FROM pg_control_checkpoint()", (before_rotation,)), (
        "checkpoint after the rotation, crash recovery would not replay it"
    )
    node.kill()
    node.poll_start()

    assert_usable(node, rotated)
    node.wait_for_catchup(standby)
    assert_usable(standby, rotated)


# An older, flushed rotation record is replayed onto the map file of a newer rotation whose
# record was lost
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="primary back on the older key: crash recovery replays the older rotation onto the newer map file",
)
def test_rotation_not_undone_by_older_record(walwriter, node, make_standby, key_name):
    crash_after_rotation(node, make_standby, key_name("rotated-key"), walwriter, flushed_key=key_name("flushed-key"))

    assert node.tde.key_info() == KeyInfo(2, "db-2", key_name("rotated-key"))


def waits_on(conn, wait_event, done, where="true", timeout=30.0):
    """True once a backend matching where waits on wait_event, False once done() holds."""
    deadline = time.monotonic() + timeout
    while not done():
        if conn.scalar(f"SELECT count(*) > 0 FROM pg_stat_activity WHERE wait_event = $1 AND {where}", (wait_event,)):
            return True
        if time.monotonic() > deadline:
            raise TimeoutError(f"neither done nor waiting on {wait_event}")
        time.sleep(0.1)
    return False


# with remote_apply the standby is on the new key when the rotation returns
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="rotation has no xid, its commit does not wait for the synchronous standby",
)
def test_rotation_waits_for_sync_standby(node, make_standby, key_name):
    rotated = KeyInfo(2, "db-2", key_name("rotated-key"))
    standby = make_standby(node)
    node.execute("ALTER SYSTEM SET synchronous_standby_names = 'standby'")
    node.execute("ALTER SYSTEM SET synchronous_commit = 'remote_apply'")
    node.execute("SELECT pg_reload_conf()")
    node.poll_until("SELECT sync_state FROM pg_stat_replication WHERE application_name = 'standby'", "sync")
    node.tde.create_key(rotated.key_name, "db-2")
    standby.execute("SELECT pg_wal_replay_pause()")
    standby.poll_until("SELECT pg_get_wal_replay_pause_state()", "paused")

    rotation = node.background(f"SELECT pg_tde_set_key_using_database_key_provider('{rotated.key_name}', 'db-2')")
    try:
        assert waits_on(node, "SyncRep", rotation.done), "rotation returned before the standby applied it"
    finally:
        standby.execute("SELECT pg_wal_replay_resume()")
    rotation.wait()
    assert standby.tde.key_info() == rotated


# not transactional: a rollback keeps the new key, on the standby too
def test_rotation_survives_rollback(node, make_standby, key_name):
    rotated = KeyInfo(2, "db-2", key_name("rotated-key"))
    standby = make_standby(node)
    node.tde.create_key(rotated.key_name, "db-2")

    with node.connect() as conn:
        conn.execute("BEGIN")
        conn.tde.set_key(rotated.key_name, "db-2")
        conn.execute("ROLLBACK")

    assert_usable(node, rotated)
    node.execute("CREATE TABLE created_after_rollback (x int) USING tde_heap")
    node.execute("INSERT INTO created_after_rollback VALUES (1)")
    node.wait_for_catchup(standby)
    assert_usable(standby, rotated)
    assert standby.scalar("SELECT x FROM created_after_rollback") == 1
    node.restart()
    assert_usable(node, rotated)


# Interrupted rotation. pg_tde_perform_rotate_key writes the re-wrapped keys to <map>.r,
# renames it over the map file, and only then writes the WAL record.
# The same points are passed during redo on a standby and in crash recovery, and in the
# default key path once per database. A backend parked with "wait" holds the pg_tde key
# lock and cannot be cancelled, only woken or killed with the server.
ENTRY_WRITTEN = "pg-tde-rotate-key-entry-written"
BEFORE_RENAME = "pg-tde-rotate-key-before-rename"
AFTER_RENAME = "pg-tde-rotate-key-after-rename"
# after the WAL record, only on the primary
LOGGED = "pg-tde-rotate-key-logged"
POINTS = [ENTRY_WRITTEN, BEFORE_RENAME, AFTER_RENAME]


def broken_after_rename(reason):
    return [
        ENTRY_WRITTEN,
        BEFORE_RENAME,
        pytest.param(AFTER_RENAME, marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)),
    ]


def initial_key(key_name):
    return KeyInfo(1, "db-1", key_name("initial-key"))


def interrupted_key(key_name):
    return KeyInfo(2, "db-2", key_name("interrupted-key"))


def key_after_crash(point, key_name):
    # current behaviour: after the rename the new map file wins, commit or not; a fix that
    # undoes the rename in recovery would give the initial key
    return interrupted_key(key_name) if point == AFTER_RENAME else initial_key(key_name)


@setup_step
def interrupt_rotation(node, injection_points, point, action, key_name, before_kill=None):
    """Rotate to the interrupted key on db-2, stopped at point by action.

    before_kill: called while the rotation waits at point, before the crash.
    """
    node.tde.create_key(key_name("interrupted-key"), "db-2")
    injection_points.attach(point, action)
    rotation = f"SELECT pg_tde_set_key_using_database_key_provider('{key_name('interrupted-key')}', 'db-2')"
    if action == "error":
        node.expect_error(f"error triggered for injection point {point}", rotation)
        injection_points.detach(point)
        return
    background = node.background(rotation)
    injection_points.wait_until_reached(point)
    if before_kill is not None:
        before_kill()
    node.kill()
    assert not background.wait(check=False).success()
    node.poll_start()


def retry_same_rotation(node, key_name, standby=None):
    node.tde.set_key(key_name("interrupted-key"), "db-2")
    assert_usable(node, interrupted_key(key_name))
    if standby is not None:
        node.wait_for_catchup(standby)
        assert_usable(standby, interrupted_key(key_name))


def assert_usable(node, key):
    assert node.tde.key_info() == key
    verify = node.try_execute("SELECT pg_tde_verify_key()")
    assert verify.success(), verify.error_message
    assert data(node) == ROWS


@pytest.mark.parametrize("point", POINTS)
def test_rotation_crash(node, make_standby, injection_points, key_name, point):
    standby = make_standby(node)
    interrupt_rotation(node, injection_points, point, "wait", key_name)

    assert_usable(node, key_after_crash(point, key_name))

    # the standby reads everything, also relations created now
    node.execute("CREATE TABLE created_after_crash (x int) USING tde_heap")
    node.execute("INSERT INTO created_after_crash VALUES (1)")
    node.wait_for_catchup(standby)
    assert data(standby) == ROWS
    assert standby.scalar("SELECT x FROM created_after_crash") == 1

    # a leftover .r file does not block retrying the same rotation, nor the next one
    if point != AFTER_RENAME:
        retry_same_rotation(node, key_name, standby)
    next_key = KeyInfo(2, "db-2", key_name("next-key"))
    rotate(node, next_key.key_name, "db-2")
    assert_usable(node, next_key)
    node.wait_for_catchup(standby)
    assert_usable(standby, next_key)
    assert standby.scalar("SELECT x FROM created_after_crash") == 1


@pytest.mark.parametrize(
    "point", broken_after_rename("primary on the new key, standby stays on the old: no WAL record")
)
def test_rotation_crash_standby_agrees(node, make_standby, injection_points, key_name, point):
    standby = make_standby(node)
    interrupt_rotation(node, injection_points, point, "wait", key_name)

    node.execute("CREATE TABLE created_after_crash (x int) USING tde_heap")
    node.wait_for_catchup(standby)
    assert standby.tde.key_info() == node.tde.key_info()


@pytest.mark.parametrize("point", POINTS)
def test_rotation_error(node, injection_points, key_name, point):
    interrupt_rotation(node, injection_points, point, "error", key_name)

    if point != AFTER_RENAME:
        assert_usable(node, initial_key(key_name))
    assert data(node) == ROWS
    node.execute("CREATE TABLE created_after_error (x int) USING tde_heap")
    node.execute("INSERT INTO created_after_error VALUES (1)")

    # current behaviour: the initial key after a restart, also after the rename; a fix that
    # keeps the renamed map file would give the interrupted key there
    node.restart()
    assert_usable(node, initial_key(key_name))
    assert node.scalar("SELECT x FROM created_after_error") == 1
    if point != AFTER_RENAME:
        retry_same_rotation(node, key_name)

    next_key = KeyInfo(2, "db-2", key_name("next-key"))
    rotate(node, next_key.key_name, "db-2")
    assert_usable(node, next_key)


# key_info, verify_key and the map file agree right after the error, without a restart
@pytest.mark.parametrize(
    "point",
    broken_after_rename(
        "key cache keeps the old key, map file has the new one; either key would do, they have to agree"
    ),
)
def test_rotation_error_session_agrees(node, injection_points, key_name, point):
    interrupt_rotation(node, injection_points, point, "error", key_name)

    assert_usable(node, node.tde.key_info())


# The record reaches the standby once flushed; the primary renamed its map file before
# writing it. Whatever the standby has, the primary has too: it is never ahead.
# Without WAL encryption the walsender takes the pg_tde key lock for every read, and waits
# for the rotation to finish; with it, it reads the WAL keys from its cache.
def test_rotation_crash_after_record_reached_standby(node, make_standby, injection_points, key_name):
    node.tde.create_key(key_name("server-key"), "global-1", scope="global")
    node.execute(f"SELECT pg_tde_set_server_key_using_global_key_provider('{key_name('server-key')}', 'global-1')")
    node.execute("ALTER SYSTEM SET pg_tde.wal_encrypt = on")
    node.restart()
    standby = make_standby(node)
    node.wait_for_catchup(standby)

    def ship_record():
        # the rotating backend holds the pg_tde key lock, flush from template1
        with node.connect("template1") as conn:
            conn.execute("SELECT pg_logical_emit_message(false, 'pg_tde_test', '', true)")
        standby.poll_until("SELECT key_name FROM pg_tde_key_info()", key_name("interrupted-key"))

    interrupt_rotation(node, injection_points, LOGGED, "wait", key_name, before_kill=ship_record)

    assert_usable(node, interrupted_key(key_name))
    node.execute("CREATE TABLE created_after_crash (x int) USING tde_heap")
    node.execute("INSERT INTO created_after_crash VALUES (1)")
    node.wait_for_catchup(standby)
    assert_usable(standby, interrupted_key(key_name))
    assert standby.scalar("SELECT x FROM created_after_crash") == 1


# A keyring is a network service. Waiting for it with the pg_tde key lock held stops
# everything else that needs the lock, in every database. The point stands for a slow
# keyring.
KEYRING_GET_KEY = "pg-tde-keyring-get-key"
KEY_LOCK = "pg_tde_tranche"


@contextlib.contextmanager
def slow_keyring_rotation(node, injection_points, key_name):
    """Rotation to a new key on db-2, waiting in the keyring call. Yields a template1 connection."""
    node.tde.create_key(key_name("slow-key"), "db-2")
    with node.connect("template1") as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS injection_points")
        injection_points.attach(KEYRING_GET_KEY, "wait")
        rotation = node.background(
            f"SELECT pg_tde_set_key_using_database_key_provider('{key_name('slow-key')}', 'db-2')"
        )
        try:
            injection_points.wait_until_reached(KEYRING_GET_KEY)
            yield conn
        finally:
            conn.execute("SELECT injection_points_detach($1)", (KEYRING_GET_KEY,))
            conn.execute("SELECT injection_points_wakeup($1)", (KEYRING_GET_KEY,))
        rotation.wait()
    assert node.tde.key_info() == KeyInfo(2, "db-2", key_name("slow-key"))


# a walsender streaming recent WAL reads it from WAL buffers, one that (re)starts reads the
# WAL files, through pg_tde
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="keyring call with the pg_tde key lock held, a (re)connecting standby waits for the lock",
)
def test_slow_keyring_does_not_stop_replication(node, make_standby, injection_points, key_name):
    standby = make_standby(node)
    node.wait_for_catchup(standby)
    standby.stop()

    with slow_keyring_rotation(node, injection_points, key_name) as conn:
        target = conn.scalar("SELECT pg_logical_emit_message(false, 'pg_tde_test', '', true)")
        standby.start()

        def received():
            return standby.scalar("SELECT coalesce(pg_last_wal_receive_lsn() >= $1::pg_lsn, false)", (target,))

        assert not waits_on(conn, KEY_LOCK, received, "backend_type = 'walsender'"), (
            "walsender waits for the pg_tde key lock"
        )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="keyring call with the pg_tde key lock held, creating an encrypted table waits for the lock",
)
@pytest.mark.parametrize("database", ["postgres", "other"])
def test_slow_keyring_does_not_stop_table_creation(node, keyring, injection_points, key_name, database):
    if database == "other":
        node.createdb("other")
        with node.connect("other") as other:
            other.tde.create_extension()
            other.tde.add_provider("other-db", keyring)
            other.tde.create_key(key_name("other-key"), "other-db")
            other.tde.set_key(key_name("other-key"), "other-db")

    with slow_keyring_rotation(node, injection_points, key_name) as conn:
        create = Background(
            node.connect(database), "CREATE TABLE /* slow keyring */ created_meanwhile (x int) USING tde_heap"
        )
        assert not waits_on(conn, KEY_LOCK, create.done, "query LIKE '%slow keyring%'"), (
            "creating an encrypted table waits for the pg_tde key lock"
        )
    create.wait()
