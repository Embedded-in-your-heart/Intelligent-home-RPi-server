"""Entry point: `python -m home_server`."""

from __future__ import annotations

import logging

from home_server.config import Config
from home_server.core.logging import setup_logging
from home_server.db import connection
from home_server.web import create_app


def main() -> None:
    config = Config.from_env()
    setup_logging(config.log_level)
    log = logging.getLogger(__name__)

    log.info("Initializing database at %s", config.db_path)
    connection.initialize(config.db_path)

    app = create_app(config)
    log.info(
        "Starting Flask app on %s:%d (debug=%s)", config.host, config.port, config.debug
    )
    app.run(host=config.host, port=config.port, debug=config.debug, use_reloader=False)


if __name__ == "__main__":
    main()
