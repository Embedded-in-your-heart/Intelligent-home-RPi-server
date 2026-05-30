"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _env_str(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    return int(raw) if raw is not None else default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    return float(raw) if raw is not None else default


@dataclass(frozen=True)
class Config:
    db_path: Path
    secret_key: str
    host: str
    port: int
    log_level: str
    ble_scan_duration: float
    reading_min_interval: float
    admin_username: str
    admin_password: str | None
    debug: bool

    @classmethod
    def from_env(cls) -> Config:
        debug = os.environ.get("HOME_SERVER_DEBUG", "0") == "1"
        secret = os.environ.get("HOME_SERVER_SECRET_KEY")
        if secret is None:
            if not debug:
                raise RuntimeError(
                    "HOME_SERVER_SECRET_KEY must be set when not running in debug mode."
                )
            secret = secrets.token_hex(32)

        return cls(
            db_path=Path(_env_str("HOME_SERVER_DB_PATH", "./data/home.db")),
            secret_key=secret,
            host=_env_str("HOME_SERVER_HOST", "0.0.0.0"),
            port=_env_int("HOME_SERVER_PORT", 5000),
            log_level=_env_str("HOME_SERVER_LOG_LEVEL", "INFO"),
            ble_scan_duration=_env_float("HOME_SERVER_BLE_SCAN_DURATION", 5.0),
            reading_min_interval=_env_float("HOME_SERVER_READING_MIN_INTERVAL", 1.0),
            admin_username=_env_str("HOME_SERVER_ADMIN_USERNAME", "admin"),
            # Empty/unset means "do not seed an admin account".
            admin_password=os.environ.get("HOME_SERVER_ADMIN_PASSWORD") or None,
            debug=debug,
        )
