from collections.abc import Callable
from typing import Any

import pytest
from stormweaver import keyrings

from pgtde.rewind import TdeRewindDriver


def _factory(
    install_dir: str, keyring: keyrings.Keyring, node_config: dict[str, str]
) -> Callable[..., TdeRewindDriver]:
    def make(cipher: str = "aes_128", *, config: dict[str, str] | None = None, **kw: Any) -> TdeRewindDriver:
        return TdeRewindDriver(
            install_dir, cipher=cipher, keyring=keyring, debug=True, config=node_config | (config or {}), **kw
        )

    return make


@pytest.fixture
def rewind_driver(
    pg_install_dir: str, sw_log_dir: Any, keyring_obj: keyrings.Keyring, node_config: dict[str, str]
) -> Callable[..., TdeRewindDriver]:
    return _factory(pg_install_dir, keyring_obj, node_config)


# pg_tde_rewind is a frontend tool, a KMIP keyring makes it very slow
@pytest.fixture
def file_rewind_driver(
    pg_install_dir: str, sw_log_dir: Any, file_keyring: keyrings.Keyring, node_config: dict[str, str]
) -> Callable[..., TdeRewindDriver]:
    return _factory(pg_install_dir, file_keyring, node_config)
