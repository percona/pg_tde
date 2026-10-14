from pathlib import Path


def archive_command(bindir: str | Path, archive: Path) -> str:
    return f'{Path(bindir) / "pg_tde_archive_decrypt"} %f %p "cp %%p {archive}/%%f"'


def restore_command(bindir: str | Path, archive: Path) -> str:
    return f'{Path(bindir) / "pg_tde_restore_encrypt"} %f %p "cp {archive}/%%f %%p"'


def archive_config(bindir: str | Path, archive: Path, *, restore: bool = False) -> dict[str, str]:
    cfg = {"archive_mode": "on", "archive_command": archive_command(bindir, archive)}
    if restore:
        cfg["restore_command"] = restore_command(bindir, archive)
    return cfg


def wal_segments(node) -> list[Path]:
    return [p for p in (node.datadir / "pg_wal").iterdir() if p.is_file() and len(p.name) == 24]


def wal_contains(node, needle: str | bytes, *, flush: bool = True) -> bool:
    # checkpoint before the switch, or the checkpoint may recycle the switched segment
    if flush:
        node.safe_sql("CHECKPOINT")
        node.safe_sql("SELECT pg_switch_wal()")
    want = needle.encode() if isinstance(needle, str) else needle
    segs = wal_segments(node)
    assert segs, "no WAL segments"
    return any(want in p.read_bytes() for p in segs)
