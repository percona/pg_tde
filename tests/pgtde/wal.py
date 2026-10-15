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


def switch_wal(node) -> str:
    # a switch on a segment holding no record is a no-op, the checkpoint record makes it real;
    # checkpoint first, a later one may recycle the switched segment
    node.safe_sql("CHECKPOINT")
    seg = node.sql_value("SELECT pg_walfile_name(pg_switch_wal())")
    assert seg is not None
    return seg


def archive_all(node) -> None:
    seg = switch_wal(node)
    node.poll_until(f"SELECT coalesce(last_archived_wal >= '{seg}', false) FROM pg_stat_archiver")


def wal_segments(node_or_dir) -> list[Path]:
    wal = node_or_dir if isinstance(node_or_dir, Path) else node_or_dir.datadir / "pg_wal"
    return [p for p in wal.iterdir() if p.is_file() and len(p.name) == 24]


def wal_contains(node_or_dir, needle: str | bytes, *, flush: bool = True) -> bool:
    # a pg_wal directory is scanned as is
    if flush and not isinstance(node_or_dir, Path):
        switch_wal(node_or_dir)
    want = needle.encode() if isinstance(needle, str) else needle
    segs = wal_segments(node_or_dir)
    assert segs, "no WAL segments"
    return any(want in p.read_bytes() for p in segs)
