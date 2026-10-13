from collections.abc import Callable
from typing import Any

import pytest
from stormweaver import keyrings

from pgtde.rewind import TdeRewindDriver


@pytest.fixture
def rewind_driver(
    pg_install_dir: str, sw_log_dir: Any, keyring_obj: keyrings.Keyring, node_config: dict[str, str]
) -> Callable[..., TdeRewindDriver]:
    def make(cipher: str = "aes_128", *, config: dict[str, str] | None = None, **kw: Any) -> TdeRewindDriver:
        return TdeRewindDriver(
            pg_install_dir, cipher=cipher, keyring=keyring_obj, debug=True, config=node_config | (config or {}), **kw
        )

    return make
