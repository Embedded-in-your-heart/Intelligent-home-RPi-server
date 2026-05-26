"""Entry point: `python -m home_server`.

Phase 1 scope: load config, init logging, init DB, start a minimal Flask app
with a /health endpoint. BLE manager and full web routes come in later phases.
"""

from __future__ import annotations

import logging

from flask import Flask

from home_server.config import Config
from home_server.core.logging import setup_logging
from home_server.db import connection


def create_app(config: Config) -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def main() -> None:
    config = Config.from_env()
    setup_logging(config.log_level)
    log = logging.getLogger(__name__)

    log.info("Initializing database at %s", config.db_path)
    connection.initialize(config.db_path)

    app = create_app(config)
    log.info("Starting Flask app on %s:%d (debug=%s)", config.host, config.port, config.debug)
    app.run(host=config.host, port=config.port, debug=config.debug, use_reloader=False)


if __name__ == "__main__":
    main()
