"""Flask application factory."""

from __future__ import annotations

from flask import Flask, g, render_template
from flask_login import LoginManager, login_required
from flask_wtf import CSRFProtect

from home_server.ble.interface import BLEManager
from home_server.ble.mock_manager import MockBLEManager
from home_server.ble.rate_limiter import RateLimiter
from home_server.config import Config
from home_server.db import users
from home_server.services.channel_service import ChannelService
from home_server.services.device_service import DeviceService
from home_server.web.db import get_conn
from home_server.web.services import CHANNEL_SERVICE_KEY, DEVICE_SERVICE_KEY


def _noop_reading(channel_id: int, value: float, timestamp: str) -> None:
    """Placeholder UI push. Phase 3e replaces this with a SocketIO emit."""


def create_app(config: Config, ble: BLEManager | None = None) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.config["DB_PATH"] = config.db_path

    if ble is None:
        ble = MockBLEManager()
    limiter = RateLimiter(config.reading_min_interval)
    app.extensions[DEVICE_SERVICE_KEY] = DeviceService(ble)
    app.extensions[CHANNEL_SERVICE_KEY] = ChannelService(ble, limiter, _noop_reading)

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

    @app.get("/")
    @login_required
    def index() -> str:
        return render_template("index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.teardown_appcontext
    def close_conn(exc: BaseException | None) -> None:
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    return app
