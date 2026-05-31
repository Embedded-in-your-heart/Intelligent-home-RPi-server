"""Entry point: `python -m home_server`."""

from __future__ import annotations

import logging

from home_server.ble.interface import DiscoveredDevice
from home_server.ble.mock_manager import MockBLEManager
from home_server.config import Config
from home_server.core.logging import setup_logging
from home_server.db import connection
from home_server.services import user_service
from home_server.web import create_app, socketio
from home_server.web.services import get_ble_runtime


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

    ble = MockBLEManager()
    # Dev demo: a couple of discoverable devices so the Scan button shows output.
    ble.scan_results = [
        DiscoveredDevice(address="C0:FF:EE:00:00:01", name="Demo Sensor", rssi=-55),
        DiscoveredDevice(address="C0:FF:EE:00:00:02", name="Demo Lamp", rssi=-61),
    ]
    app = create_app(config, ble=ble)

    with app.app_context():
        runtime = get_ble_runtime()
        runtime.activate()
        if isinstance(ble, MockBLEManager):
            ble.start(runtime.make_feed(), interval_s=1.0)

    log.info(
        "Starting server on %s:%d (debug=%s)", config.host, config.port, config.debug
    )
    socketio.run(
        app,
        host=config.host,
        port=config.port,
        debug=config.debug,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":
    main()
