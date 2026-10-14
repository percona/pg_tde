from pathlib import Path

import pytest

from pgtde import upgrade

pytestmark = pytest.mark.linux_only  # sh stubs


def _fake_install(tmp_path: Path, name: str, major: int, tde: str) -> Path:
    # pg_config stub answering the flags PgInstall.from_pg_config asks for
    root = tmp_path / name
    (root / "bin").mkdir(parents=True)
    ext = root / "share" / "extension"
    ext.mkdir(parents=True)
    (ext / "pg_tde.control").write_text(f"default_version = '{tde}'\n")
    pc = root / "bin" / "pg_config"
    pc.write_text(
        "#!/bin/sh\n"
        f'case "$1" in --bindir) echo {root}/bin;; --version) echo "PostgreSQL {major}.1";;\n'
        f"--pkglibdir) echo {root}/lib;; --sharedir) echo {root}/share;; esac\n"
    )
    pc.chmod(0o755)
    return pc


def test_parse_dir_entries_and_labels(tmp_path):
    suite = _fake_install(tmp_path, "new", 18, "2.2")
    a = _fake_install(tmp_path, "a", 17, "2.2")
    b = _fake_install(tmp_path, "b", 18, "2.1")
    srcs = upgrade.parse_sources([f"{a},{b}", str(a)], upgrade.load_install(suite))
    assert [s.label for s in srcs] == ["pg17-tde2.2", "pg18-tde2.1", "pg17-tde2.2-2"]
    assert [s.same_major for s in srcs] == [False, True, False]
    assert [s.tde_differs for s in srcs] == [False, True, False]
    assert all(s.side_by_side for s in srcs)


def test_script_entry_switches_and_probes(tmp_path):
    suite = _fake_install(tmp_path, "new", 18, "2.2")
    state = tmp_path / "state"
    script = tmp_path / "switch.sh"
    ctl = tmp_path / "new" / "share" / "extension" / "pg_tde.control"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> {state}\n'
        f"""if [ "$2" = old ]; then v=$1; else v=2.2; fi; echo "default_version = '$v'" > {ctl}\n"""
    )
    script.chmod(0o755)
    ctl.write_text("default_version = '2.1'\n")  # left switched to old
    (src,) = upgrade.parse_sources([f"script:{script} 2.1"], upgrade.load_install(suite))
    assert src.label == "pg18-tde2.1"
    assert src.suite_tde == "2.2"
    assert src.same_major and src.tde_differs and not src.side_by_side
    assert state.read_text().split("\n")[:3] == ["2.1 new", "2.1 old", "2.1 new"]
    src.switch_old()
    src.switch_old()  # no-op, already old
    src.switch_new()
    assert state.read_text().count("old") == 2


def test_gate_mismatch_reason(tmp_path):
    suite = _fake_install(tmp_path, "new", 18, "2.2")
    a = _fake_install(tmp_path, "a", 17, "2.2")
    (src,) = upgrade.parse_sources([str(a)], upgrade.load_install(suite))
    assert upgrade.gate_mismatch(src, {"same_major": True}) == "pg17-tde2.2: needs same_major=True"
    assert upgrade.gate_mismatch(src, {"same_major": False}) is None
    with pytest.raises(ValueError):
        upgrade.gate_mismatch(src, {"bogus": True})


def test_failing_script_raises(tmp_path):
    suite = _fake_install(tmp_path, "new", 18, "2.2")
    script = tmp_path / "bad.sh"
    script.write_text("#!/bin/sh\nexit 3\n")
    script.chmod(0o755)
    with pytest.raises(RuntimeError, match="exit status 3"):
        upgrade.parse_sources([f"script:{script}"], upgrade.load_install(suite))


def test_failed_probe_switches_back(tmp_path):
    suite = _fake_install(tmp_path, "new", 18, "2.2")
    state = tmp_path / "state"
    script = tmp_path / "switch.sh"
    ctl = tmp_path / "new" / "share" / "extension" / "pg_tde.control"
    script.write_text(f'#!/bin/sh\necho "$1" >> {state}\nif [ "$1" = old ]; then rm -f {ctl}; fi\n')
    script.chmod(0o755)
    with pytest.raises(FileNotFoundError):
        upgrade.parse_sources([f"script:{script}"], upgrade.load_install(suite))
    assert state.read_text().split() == ["new", "old", "new"]


def test_script_after_comma_rejected(tmp_path):
    suite = _fake_install(tmp_path, "new", 18, "2.2")
    with pytest.raises(ValueError, match="own --old-pg-config value"):
        upgrade.parse_sources([f"{suite}, script:/bin/true"], upgrade.load_install(suite))


def test_script_value_stripped(tmp_path):
    suite = _fake_install(tmp_path, "new", 18, "2.2")
    (src,) = upgrade.parse_sources(["  script:/bin/true "], upgrade.load_install(suite))
    assert src.command == ["/bin/true"]
