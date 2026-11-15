import pytest

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
