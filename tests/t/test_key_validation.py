import struct

from stormweaver.keyrings.file import FileKeyring

from pgtde import api

# TDE_KEY_NAME_LEN + MAX_KEY_DATA_SIZE, see src/include/keyring/keyring_api.h
KEY_LEN_OFFSET = 256 + 32


def _corrupt(path):
    with open(path, "r+b") as f:
        f.seek(KEY_LEN_OFFSET)
        f.write(struct.pack("=I", 0))
        f.seek(KEY_LEN_OFFSET, 1)
        f.write(struct.pack("=I", 0xFFFFFFFF))


def _set_key_fails(node, key, warning):
    off = node.log_offset()
    res = node.expect_error(
        rf'failed to retrieve principal key "{key}" from key provider "test-file-provider"',
        f"SELECT pg_tde_set_key_using_database_key_provider('{key}', 'test-file-provider')",
    )
    assert "Invalid key" in res.error_message
    node.wait_for_log(rf"WARNING:  {warning}", offset=off, timeout=5)


def test_key_validation(tde_node, tmp_path):
    node = tde_node
    kr = FileKeyring(tmp_path / "db.keys")
    api.create_extension(node)
    api.add_provider(node, kr, "test-file-provider")
    api.create_key(node, "key1", "test-file-provider")
    api.create_key(node, "key2", "test-file-provider")
    _corrupt(kr.path)

    _set_key_fails(node, "key1", r"invalid key: data length is zero")
    _set_key_fails(node, "key2", r'invalid key: unsupported key length "4294967295"')
