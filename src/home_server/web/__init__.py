"""Flask application factory."""

from __future__ import annotations

from typing import Any

from flask import Flask, g, render_template
from flask_login import LoginManager, current_user, login_required
from flask_socketio import SocketIO, join_room, leave_room
from flask_wtf import CSRFProtect

from home_server.ble.interface import BLEManager
from home_server.ble.mock_manager import MockBLEManager
from home_server.ble.rate_limiter import RateLimiter
from home_server.config import Config
from home_server.db import channels as db_channels
from home_server.db import connection, users
from home_server.db import devices as db_devices
from home_server.services.ble_runtime import BleRuntime
from home_server.services.channel_service import ChannelService
from home_server.services.device_service import DeviceService
from home_server.web.db import get_conn
from home_server.web.services import (
    BLE_RUNTIME_KEY,
    CHANNEL_SERVICE_KEY,
    DEVICE_SERVICE_KEY,
)

socketio = SocketIO()


def _emit_reading(channel_id: int, value: float, timestamp: str) -> None:
    """UI push: send each notify to the per-channel SocketIO room."""
    socketio.emit(
        "reading",
        {"channel_id": channel_id, "value": value, "timestamp": timestamp},
        room=f"channel:{channel_id}",
    )


def _emit_device_status(device_id: int, status: str) -> None:
    """UI push: broadcast a device connection-status change to all clients."""
    socketio.emit("device_status", {"device_id": device_id, "status": status})


@socketio.on("connect")
def _on_connect() -> bool:
    """Reject anonymous WebSocket clients (all HTTP routes require login too)."""
    return bool(current_user.is_authenticated)


@socketio.on("subscribe_channel")
def _on_subscribe_channel(data: dict[str, Any]) -> None:
    channel_id = data.get("channel_id")
    if channel_id is not None:
        join_room(f"channel:{channel_id}")


@socketio.on("unsubscribe_channel")
def _on_unsubscribe_channel(data: dict[str, Any]) -> None:
    channel_id = data.get("channel_id")
    if channel_id is not None:
        leave_room(f"channel:{channel_id}")


def create_app(config: Config, ble: BLEManager | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.config["DB_PATH"] = config.db_path
    app.config["BLE_SCAN_DURATION"] = config.ble_scan_duration

    from home_server.presets import load_presets

    app.config["CHANNEL_PRESETS"] = load_presets(config.channel_presets_path)

    socketio.init_app(app, async_mode="threading")

    if ble is None:
        ble = MockBLEManager()
    limiter = RateLimiter(config.reading_min_interval)
    channel_service = ChannelService(ble, limiter, _emit_reading)
    device_service = DeviceService(ble, scan_name_prefix=config.scan_name_prefix)
    app.extensions[DEVICE_SERVICE_KEY] = device_service
    app.extensions[CHANNEL_SERVICE_KEY] = channel_service
    app.extensions[BLE_RUNTIME_KEY] = BleRuntime(
        ble,
        channel_service,
        conn_factory=lambda: connection.connect(config.db_path),
        scan_duration=config.ble_scan_duration,
        on_status=_emit_device_status,
    )

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    CSRFProtect(app)

    from home_server.web.auth import LoginUser
    from home_server.web.auth import bp as auth_bp

    @login_manager.user_loader
    def load_user(user_id: str) -> LoginUser | None:
        user = users.get_by_id(get_conn(), int(user_id))
        return LoginUser(user) if user is not None else None

    app.register_blueprint(auth_bp)

    from home_server.web.devices import bp as devices_bp

    app.register_blueprint(devices_bp)

    from home_server.web.channels import bp as channels_bp

    app.register_blueprint(channels_bp)

    @app.get("/")
    @login_required
    def index() -> str:
        conn = get_conn()
        overview = [
            (
                d,
                "connected" if device_service.is_connected(d.address) else "disconnected",
                db_channels.list_by_device(conn, d.id),
            )
            for d in db_devices.list_all(conn)
        ]
        return render_template("index.html", overview=overview)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.teardown_appcontext
    def close_conn(exc: BaseException | None) -> None:
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    return app
