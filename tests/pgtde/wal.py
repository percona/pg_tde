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
