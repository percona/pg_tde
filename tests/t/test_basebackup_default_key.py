from pgtde import api


def test_basebackup_default_key(tde_node, keyring_obj, tmp_path):
    node = tde_node
    node.setup_default_key(keyring_obj, provider="file-provider", key="key1")
    # server key used to materialize only on next start, -E backup failed
    assert api.server_key_info(node) == ["-1", "file-provider", "key1"]
    node.tde_basebackup(tmp_path / "bk", "-X", "stream")
