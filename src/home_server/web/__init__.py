"""Flask application factory."""

from __future__ import annotations

from flask import Flask, g, render_template
from flask_login import LoginManager, login_required
from flask_wtf import CSRFProtect

from home_server.config import Config
from home_server.db import users
from home_server.web.db import get_conn


def create_app(config: Config) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.config["DB_PATH"] = config.db_path

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
