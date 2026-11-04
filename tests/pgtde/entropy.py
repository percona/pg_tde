import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 64 * 1024
_ENTROPY_THRESHOLD = 0.8


class EncryptionMismatchError(Exception):
    pass


def calculate_entropy(path: str) -> float:
    """Shannon entropy of a file's bytes, log base 256 (0.0 .. 1.0)."""
    histogram = [0] * 256
    total = 0
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            for byte in chunk:
                histogram[byte] += 1
            total += len(chunk)
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in histogram:
        if count:
            p = count / total
            entropy -= p * math.log(p, 256)
    return entropy


def verify_entropy(relname: str, tablename: str, tableam: str, is_encrypted: bool, path: str) -> None:
    """Cross-check a relation file against its expected encryption state.

    Raises EncryptionMismatchError when the catalog says one thing
    (pg_tde_is_encrypted) and the access method says another. Entropy
    that merely looks suspicious only warns: a nearly-empty encrypted
    file legitimately has low entropy, and a compressible-but-plain
    file can score high.
    """
    entropy = calculate_entropy(path)
    if tableam == "tde_heap":
        if not is_encrypted:
            raise EncryptionMismatchError(
                f"table {tablename} rel {relname}: tde_heap but not encrypted (file {path}, entropy {entropy:.3f})"
            )
        if entropy != 0 and entropy < _ENTROPY_THRESHOLD:
            logger.warning("entropy of %s for table %s is too low: %.3f", path, tablename, entropy)
    else:
        if is_encrypted:
            raise EncryptionMismatchError(
                f"table {tablename} rel {relname}: {tableam} but encrypted (file {path}, entropy {entropy:.3f})"
            )
        if entropy > _ENTROPY_THRESHOLD:
            logger.warning("%s for table %s is not encrypted but has high entropy: %.3f", path, tablename, entropy)


_LIST_TABLES = """
    select pg_relation_filepath(c.oid), c.relname, a.amname, c.oid, pg_tde_is_encrypted(c.oid)
    from pg_class c join pg_am a on a.oid = c.relam
    where c.relkind in ('r', 'm')
        and c.relname not like 'pg_%' and c.relname not like 'sql_%'
"""


def _dependent_files_query(oid: str) -> str:
    # indexes/toast of the given relation, same query the lua helper used
    return f"""
        select pg_relation_filepath(c.oid), c.relname, pg_tde_is_encrypted(c.oid)
        from pg_class c
        join pg_attribute a on a.attrelid = {oid}
        join pg_depend d on d.objid = c.oid and d.deptype in ('i', 'a') and a.attrelid = {oid}
        where d.refobjid = {oid} group by c.oid
    """


def db_files_entropy(conn: Any, datadir: str) -> None:
    """Verify encryption consistency of every user relation file on disk.

    Requires pg_tde in the target database (uses pg_tde_is_encrypted).
    """
    result = conn.execute(_LIST_TABLES)
    if not result.success():
        raise RuntimeError(f"listing tables failed: {result.error_message}")
    for row in result.rows():
        filepath, relname, amname, oid, encrypted = row
        if filepath is None:
            continue
        assert relname is not None
        assert amname is not None
        assert oid is not None
        verify_entropy(relname, relname, amname, encrypted == "t", os.path.join(datadir, filepath))
        deps = conn.execute(_dependent_files_query(oid))
        if not deps.success():
            raise RuntimeError(f"listing dependents of {relname} failed: {deps.error_message}")
        # dependent objects inherit the parent table's encryption expectation
        for dep_row in deps.rows():
            dep_path, dep_name, dep_encrypted = dep_row
            if dep_path is None:
                continue
            assert dep_name is not None
            verify_entropy(dep_name, relname, amname, dep_encrypted == "t", os.path.join(datadir, dep_path))
