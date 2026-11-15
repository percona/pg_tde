# What the on disk checks prove. A byte search only means something for files that
# would contain the plaintext if they were not encrypted:
# - the files of rel itself and of its toast table (rel is a table, matview, toast table or
#   index with the plaintext in it),
# - the files of the indexes of rel, if one of them indexes a column with the plaintext.
# assert_plain_on_disk shows the plaintext in both on a plain twin, so "not in the files" on
# the encrypted side has a witness for each of them. The toast index, indexes on other
# columns and the fsm/vm forks never contain the plaintext: for those only the
# pg_tde_is_encrypted() catalog check says anything.
# "Not in the files" only means something for files with data: the encrypted side
# requires the files of rel itself to be non-empty (not those of its toast or indexes).
# A partitioned table is checked leaf by leaf, so every leaf needs data on disk.

# sequence_magic in the special space of a sequence page (commands/sequence.c)
_SEQ_MAGIC = b"\x17\x17\x00\x00"
_SEQ_MAGIC_OFFSET = 8192 - 8


def _own_bytes(node, rel: str, checkpoint: bool = False, with_toast: bool = False) -> bytes:
    return node.relation_bytes(rel, with_toast=with_toast, with_indexes=False, checkpoint=checkpoint)


def _index_bytes(node, rel: str) -> bytes | None:
    """Files of the indexes of rel, None if it has none. Toast indexes are left out."""
    if node.scalar("SELECT relkind FROM pg_class WHERE oid = $1::regclass", (rel,)) == "t":
        return None
    indexes = node.query("SELECT indexrelid::regclass::text FROM pg_index WHERE indrelid = $1::regclass", (rel,))
    if not indexes:
        return None
    return b"".join(_own_bytes(node, i.indexrelid) for i in indexes)


def _encrypted(node, rel: str, plaintext: str) -> None:
    for r in node.related_relations(rel):
        assert node.tde.is_encrypted(r), f"{r} is not encrypted according to pg_tde"
    own = _own_bytes(node, rel, checkpoint=True, with_toast=True)
    assert _own_bytes(node, rel), f"{rel} has no data on disk"
    assert plaintext.encode() not in own, f"{plaintext!r} is readable on disk in {rel}"
    indexes = _index_bytes(node, rel)
    if indexes is not None:
        assert plaintext.encode() not in indexes, f"{plaintext!r} is readable on disk in an index of {rel}"


def _plain(node, rel: str, plaintext: str) -> None:
    for r in node.related_relations(rel):
        assert not node.tde.is_encrypted(r), f"{r} is encrypted according to pg_tde"
    own = _own_bytes(node, rel, checkpoint=True, with_toast=True)
    assert plaintext.encode() in own, f"{plaintext!r} not found on disk in {rel}"
    indexes = _index_bytes(node, rel)
    if indexes is not None:
        assert plaintext.encode() in indexes, f"{plaintext!r} not found on disk in the indexes of {rel}"


def _check_tree(node, rel: str, plaintext: str, check) -> None:
    """check on rel, or on every leaf partition when rel is partitioned."""
    if node.tde.encryption_state(rel) is not None:
        check(node, rel, plaintext)
        return
    assert node.scalar("SELECT relkind FROM pg_class WHERE oid = $1::regclass", (rel,)) == "p", (
        f"{rel} has no storage and is not a partitioned table"
    )
    tree = node.query("SELECT relid::regclass::text AS rel, isleaf FROM pg_partition_tree($1::regclass)", (rel,))
    for r in [r for t in tree if not t.isleaf for r in node.related_relations(t.rel)]:
        assert node.tde.encryption_state(r) is None, f"{r} has no storage, pg_tde reports a state for it"
    leaves = [t.rel for t in tree if t.isleaf]
    assert leaves, f"{rel} has no leaf partitions"
    node.execute("CHECKPOINT")
    empty = [f"leaf {leaf} has no data on disk" for leaf in leaves if not _own_bytes(node, leaf)]
    assert not empty, f"{rel}: the check needs data in every leaf\n" + "\n".join(empty)
    differ = []
    for leaf in leaves:
        try:
            check(node, leaf, plaintext)
        except AssertionError as e:
            differ.append(f"{leaf}: {e}")
    assert not differ, f"leaf partitions of {rel} that differ:\n" + "\n".join(differ)


def assert_encrypted_on_disk(node, rel: str, plaintext: str) -> None:
    """rel, its toast and its indexes are encrypted according to pg_tde, and plaintext is not
    in the files of rel, its toast table and its indexes; the files of rel itself are not
    empty. For a partitioned table: the same for every leaf, so every leaf needs data; the
    tree members without storage have no state."""
    _check_tree(node, rel, plaintext, _encrypted)


def assert_plain_on_disk(node, rel: str, plaintext: str) -> None:
    """rel, its toast and its indexes are not encrypted according to pg_tde, plaintext is in the
    files of rel or its toast table, and in the files of its indexes if it has any (one of them
    has to index the plaintext). Partitioned tables like assert_encrypted_on_disk, every leaf
    needs data."""
    _check_tree(node, rel, plaintext, _plain)


def _sequence_magic_on_disk(node, seq: str) -> bool:
    page = _own_bytes(node, seq, checkpoint=True)
    assert len(page) >= 8192, f"{seq}: only {len(page)} bytes on disk"
    return page[_SEQ_MAGIC_OFFSET : _SEQ_MAGIC_OFFSET + 4] == _SEQ_MAGIC


def assert_sequence_encrypted_on_disk(node, seq: str) -> None:
    assert node.tde.is_encrypted(seq), f"{seq} is not encrypted according to pg_tde"
    assert not _sequence_magic_on_disk(node, seq), f"plain sequence page on disk for {seq}"


def assert_sequence_plain_on_disk(node, seq: str) -> None:
    assert not node.tde.is_encrypted(seq), f"{seq} is encrypted according to pg_tde"
    assert _sequence_magic_on_disk(node, seq), f"no plain sequence page on disk for {seq}"
