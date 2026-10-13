from pathlib import Path

from stormweaver.backends.postgres import Postgres
from stormweaver.testing import alloc_port, ensure_logging

from pgtde.node import TdeNode


def standby_from_backup_dir(
    backup: Path, install_dir: str | Path, *, name: str, config: dict[str, str] | None = None
) -> TdeNode:
    # like PgTestNode.from_backup, but no primary_conninfo and not started,
    # so the caller can take a log offset first
    ensure_logging()
    datadir = backup.parent / name
    if datadir != backup:
        backup.rename(datadir)
    port = alloc_port()
    pg = Postgres(install_dir, datadir, init=False, port=port)
    pg.add_config({"port": str(port), "unix_socket_directories": str(datadir.resolve().parent)})
    if config:
        pg.add_config(config)
    pg.set_signal("standby")
    node = TdeNode(pg, "postgres", name)
    parent = datadir.parent
    if parent.parent == Path("/tmp") and parent.name.startswith("sw-backup-"):
        node._owned_dir = parent
    return node
