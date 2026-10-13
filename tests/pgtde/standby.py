from pathlib import Path

from pgtde.node import TdeNode


def standby_from_backup_dir(
    backup: Path, install_dir: str | Path, *, name: str, config: dict[str, str] | None = None
) -> TdeNode:
    # like PgTestNode.from_backup, but no primary_conninfo and not started,
    # so the caller can take a log offset first
    datadir = backup.parent / name
    if datadir != backup:
        backup.rename(datadir)
    node = TdeNode.adopt(install_dir, datadir, name=name, config=config)
    node.db.set_signal("standby")
    parent = datadir.parent
    if parent.parent == Path("/tmp") and parent.name.startswith("sw-backup-"):
        node._owned_dir = parent
    return node
