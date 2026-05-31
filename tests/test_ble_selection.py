import sys

import pytest

from home_server.ble.mock_manager import MockBLEManager
from home_server.ble.selection import select_ble_manager
from home_server.config import Config

_ON_LINUX = sys.platform.startswith("linux")


def test_mock_backend_returns_mock() -> None:
    assert isinstance(select_ble_manager("mock", "linux"), MockBLEManager)


def test_auto_non_linux_returns_mock() -> None:
    assert isinstance(select_ble_manager("auto", "darwin"), MockBLEManager)


def test_unknown_backend_raises() -> None:
    with pytest.raises(ValueError):
        select_ble_manager("nonsense", "linux")


@pytest.mark.skipif(_ON_LINUX, reason="bluepy may import on Linux; fallback only on non-Linux")
def test_auto_linux_falls_back_to_mock_when_bluepy_unavailable() -> None:
    assert isinstance(select_ble_manager("auto", "linux"), MockBLEManager)


@pytest.mark.skipif(_ON_LINUX, reason="bluepy import only fails on non-Linux")
def test_bluepy_backend_raises_on_non_linux() -> None:
    with pytest.raises(ImportError):
        select_ble_manager("bluepy", "linux")


def test_config_ble_backend_default_and_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME_SERVER_DEBUG", "1")
    monkeypatch.delenv("HOME_SERVER_BLE_BACKEND", raising=False)
    assert Config.from_env().ble_backend == "auto"
    monkeypatch.setenv("HOME_SERVER_BLE_BACKEND", "mock")
    assert Config.from_env().ble_backend == "mock"
