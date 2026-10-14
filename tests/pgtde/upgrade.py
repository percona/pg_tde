import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stormweaver.pginstall import PgInstall

GATES = ("same_major", "tde_differs", "side_by_side")


def load_install(pg_config: str | Path) -> PgInstall:
    return PgInstall.from_pg_config(pg_config)


def control_version(pi: PgInstall) -> str:
    assert pi.sharedir is not None
    text = (Path(pi.sharedir) / "extension" / "pg_tde.control").read_text()
    m = re.search(r"default_version\s*=\s*'([^']+)'", text)
    if not m:
        raise RuntimeError(f"no default_version in pg_tde.control of {pi.install_dir}")
    return m.group(1)


def run_script(command: list[str], which: str) -> None:
    cp = subprocess.run([*command, which], capture_output=True, text=True)
    if cp.returncode != 0:
        raise RuntimeError(f"{shlex.join(command)} {which}: exit status {cp.returncode}\n{cp.stdout}{cp.stderr}")


@dataclass
class UpgradeSource:
    suite: PgInstall
    suite_tde: str
    old: PgInstall
    old_tde: str
    command: list[str] | None = None
    label: str = ""
    _state: str = field(default="new", repr=False)

    @property
    def mode(self) -> str:
        return "dir" if self.command is None else "script"

    @property
    def major(self) -> int | None:
        return self.old.major

    @property
    def same_major(self) -> bool:
        return self.old.major == self.suite.major

    @property
    def tde_differs(self) -> bool:
        return self.old_tde != self.suite_tde

    @property
    def side_by_side(self) -> bool:
        return self.command is None

    def _run(self, which: str) -> None:
        assert self.command is not None
        run_script(self.command, which)
        self._state = which

    def switch_old(self) -> None:
        if self.command is not None and self._state != "old":
            self._run("old")

    def switch_new(self) -> None:
        if self.command is not None and self._state != "new":
            self._run("new")

    def old_node(self, factory: Callable[..., Any], name: str, **kw: Any) -> Any:
        self.switch_old()
        return factory(name, install=self.old, **kw)

    def new_node(self, factory: Callable[..., Any], name: str, old_node: Any, **kw: Any) -> Any:
        # pg_upgrade target: not started, checksums like the old cluster
        # old_node must still be running here
        checksums = old_node.sql_value("SHOW data_checksums") == "on"
        self.switch_new()
        new_default_on = (self.suite.major or 0) >= 18
        if checksums != new_default_on:
            flag = "--data-checksums" if checksums else "--no-data-checksums"
            kw["extra_initdb_args"] = [*(kw.get("extra_initdb_args") or []), flag]
        return factory(name, start=False, **kw)

    def start_in_place(self, node: Any) -> None:
        # same datadir on the new binaries, then update the extension everywhere
        assert self.same_major, f"{self.label}: start_in_place needs same_major"
        if node.db.is_running():
            node.stop()
        self.switch_new()
        node.db.install_dir = Path(self.suite.install_dir)
        node.start()
        update_extension(node)

    def run_pg_tde_upgrade(
        self, old_node: Any, new_node: Any, *extra: str | Path, socketdir: str | Path, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        assert self.side_by_side, f"{self.label}: pg_tde_upgrade needs both installs on disk"
        if old_node.db.is_running():
            old_node.stop()
        return new_node.tool(
            "pg_tde_upgrade",
            "--no-sync",
            "--old-datadir",
            old_node.datadir,
            "--new-datadir",
            new_node.datadir,
            "--old-bindir",
            self.old.bindir,
            "--new-bindir",
            self.suite.bindir,
            "--socketdir",
            socketdir,
            "--old-port",
            str(old_node.port),
            "--new-port",
            str(new_node.port),
            *extra,
            cwd=cwd,
        )


def update_extension(node: Any) -> None:
    for (db,) in node.safe_sql("SELECT datname FROM pg_database WHERE datallowconn ORDER BY datname"):
        with node.connect(db) as conn:
            if conn.sql_value("SELECT count(*) FROM pg_extension WHERE extname = 'pg_tde'") == "1":
                conn.safe_sql("ALTER EXTENSION pg_tde UPDATE")


def gate_mismatch(src: UpgradeSource, gates: dict[str, bool]) -> str | None:
    for k, want in gates.items():
        if k not in GATES:
            raise ValueError(f"unknown old_install gate {k!r}, known: {', '.join(GATES)}")
        if getattr(src, k) != want:
            return f"{src.label}: needs {k}={want}"
    return None


def is_script(value: str) -> bool:
    return value.strip().startswith("script:")


def _split(values: list[str]) -> list[str | list[str]]:
    # pg_config paths, or a script command line, which may contain commas
    out: list[str | list[str]] = []
    for v in values:
        if is_script(v):
            out.append(shlex.split(v.strip()[len("script:") :]))
            continue
        for x in v.split(","):
            if is_script(x):
                raise ValueError(f"{x.strip()!r}: a script: entry must be its own --old-pg-config value")
            if x.strip():
                out.append(x.strip())
    return out


def parse_sources(values: list[str], suite: PgInstall) -> list[UpgradeSource]:
    specs = _split(values)
    scripts = [s for s in specs if isinstance(s, list)]
    if scripts:
        # the install may have been left switched to old, probe it as new
        for cmd in scripts:
            run_script(cmd, "new")
        assert suite.pg_config is not None
        suite = load_install(suite.pg_config)
    suite_tde = control_version(suite)
    srcs: list[UpgradeSource] = []
    seen: dict[str, int] = {}
    for spec in specs:
        if isinstance(spec, list):
            src = UpgradeSource(suite, suite_tde, suite, suite_tde, command=spec)
            src.switch_old()
            try:
                assert suite.pg_config is not None
                src.old = load_install(suite.pg_config)
                src.old_tde = control_version(src.old)
            finally:
                src.switch_new()
        else:
            old = load_install(spec)
            src = UpgradeSource(suite, suite_tde, old, control_version(old))
        base = f"pg{src.major}-tde{src.old_tde}"
        seen[base] = seen.get(base, 0) + 1
        src.label = base if seen[base] == 1 else f"{base}-{seen[base]}"
        srcs.append(src)
    return srcs
