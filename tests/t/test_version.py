import re

from pgtde import api


def test_version(tde_node, pg_install, pg_major):
    api.create_extension(tde_node)
    v = api.version(tde_node)
    m = re.fullmatch(r"pg_tde (\d+\.\d+)\.\d+", v)
    assert m, v
    control = (pg_install.sharedir / "extension" / "pg_tde.control").read_text()
    default_version = re.search(r"default_version\s*=\s*'([^']+)'", control).group(1)
    assert m.group(1) == default_version
    if pg_major >= 18:
        rows = tde_node.safe_sql(
            "SELECT module_name, version FROM pg_get_loaded_modules() WHERE file_name IN ('pg_tde.so', 'pg_tde.dylib')"
        )
        assert rows == [["pg_tde", v.split()[1]]]
