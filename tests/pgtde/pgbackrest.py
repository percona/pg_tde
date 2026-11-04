import configparser
import json
import re
import shutil
import subprocess
from pathlib import Path

import stormweaver.testing as st

_SEGMENT = re.compile(r"[0-9A-F]{24}-[0-9a-f]{40}(\.\w+)?")


class Stanza:
    # decrypt: archive through pg_tde_archive_decrypt (plaintext WAL in the repo),
    # else the repo keeps the ciphertext WAL as written to pg_wal
    def __init__(self, node, repo: Path, name: str = "main", *, decrypt: bool = True, **options: str) -> None:
        exe = shutil.which("pgbackrest")
        assert exe, "pgbackrest not on PATH"
        self.exe = exe
        self.repo = repo
        self.name = name
        self.decrypt = decrypt
        self.options = options
        self.conf = repo / "pgbackrest.conf"
        self.retarget(node)

    def retarget(self, node) -> None:
        self.node = node
        cfg = configparser.ConfigParser(interpolation=None)
        cfg["global"] = {
            "repo1-path": str(self.repo),
            "log-path": str(self.repo / "log"),
            "lock-path": str(self.repo / "lock"),
            "spool-path": str(self.repo / "spool"),
            "log-level-console": "warn",
        } | {k.replace("_", "-"): v for k, v in self.options.items()}
        cfg[self.name] = {
            "pg1-path": str(node.datadir),
            "pg1-port": str(node.port),
            "pg1-socket-path": node.sql_value("SHOW unix_socket_directories"),
        }
        for d in ("log", "lock", "spool"):
            (self.repo / d).mkdir(parents=True, exist_ok=True)
        with open(self.conf, "w") as f:
            cfg.write(f)

    def _argv(self, *args: str | Path) -> list[str]:
        return [self.exe, f"--config={self.conf}", f"--stanza={self.name}", *(str(a) for a in args)]

    def _cmd(self, *args: str) -> str:
        return " ".join(self._argv(*args))

    def _bindir(self) -> Path:
        return Path(self.node.db.install_dir) / "bin"

    def archive_command(self) -> str:
        if not self.decrypt:
            # %p is relative to the datadir
            return self._cmd(f"--pg1-path={self.node.datadir}", "archive-push", "%p")
        return f'{self._bindir() / "pg_tde_archive_decrypt"} %f %p "{self._cmd("archive-push", "%%p")}"'

    def restore_command(self, datadir: Path | None = None) -> str:
        pg1 = f"--pg1-path={datadir or self.node.datadir}"
        if not self.decrypt:
            return self._cmd(pg1, "archive-get", "%f", "%p")
        return f'{self._bindir() / "pg_tde_restore_encrypt"} %f %p "{self._cmd(pg1, "archive-get", "%%f", "%%p")}"'

    def archive_config(self) -> dict[str, str]:
        return {"archive_mode": "on", "archive_command": self.archive_command()}

    def run(self, *args: str | Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(self._argv(*args), capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def _ok(self, *args: str | Path) -> subprocess.CompletedProcess[str]:
        cp = self.run(*args)
        st.command_ok(cp, f"pgbackrest {' '.join(str(a) for a in args)}")
        return cp

    def create(self) -> None:
        self._ok("stanza-create")

    def check(self) -> None:
        self._ok("check")

    def backup(self, type: str = "full") -> None:
        self._ok(f"--type={type}", "backup")

    def info(self) -> list[dict]:
        return json.loads(self._ok("--output=json", "info").stdout)

    def restore(self, target_datadir: Path, *extra: str) -> Path:
        self._ok(
            "restore",
            f"--pg1-path={target_datadir}",
            f"--recovery-option=restore_command={self.restore_command(target_datadir)}",
            *extra,
        )
        return target_datadir

    def archived_segments(self) -> list[Path]:
        # <segment>-<sha1>[.gz|.lz4|...], not the .history / .backup files
        return sorted(p for p in (self.repo / "archive" / self.name).rglob("*") if _SEGMENT.fullmatch(p.name))
