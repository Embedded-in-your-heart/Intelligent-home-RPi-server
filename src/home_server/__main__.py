"""Entry point: `python -m home_server`."""

from __future__ import annotations

import logging

from home_server.config import Config
from home_server.core.logging import setup_logging
from home_server.db import connection
from home_server.services import user_service
from home_server.web import create_app


def _seed_admin(config: Config, log: logging.Logger) -> None:
    if not config.admin_password:
        return
    conn = connection.connect(config.db_path)
    try:
        created = user_service.seed_admin(
            conn, username=config.admin_username, password=config.admin_password
        )
        if created:
            log.info("Seeded admin account %r", config.admin_username)
        else:
            log.info("Admin account %r already exists; left unchanged", config.admin_username)
    except user_service.WeakPasswordError as e:
        log.warning("Skipping admin seed (weak password): %s", e)
    finally:
        conn.close()


def main() -> None:
    config = Config.from_env()
    setup_logging(config.log_level)
    log = logging.getLogger(__name__)

    log.info("Initializing database at %s", config.db_path)
    connection.initialize(config.db_path)
    _seed_admin(config, log)

    app = create_app(config)
    log.info(
        "Starting Flask app on %s:%d (debug=%s)", config.host, config.port, config.debug
    )
    app.run(host=config.host, port=config.port, debug=config.debug, use_reloader=False)


if __name__ == "__main__":
    main()
