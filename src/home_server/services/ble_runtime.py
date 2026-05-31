"""Wire BLE notify subscriptions to the channel service and feed the mock.

Constructed (inert) by the application factory and stored in app.extensions.
`activate()` connects known devices and subscribes their display channels —
it has side effects (connections, callbacks) and is invoked only from
`__main__`, never at app-construction time, so tests stay thread-free.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from collections.abc import Callable

from home_server.ble import parser
from home_server.ble.interface import BLEManager
from home_server.db import channels, devices
from home_server.db.channels import Channel
from home_server.services.channel_service import ChannelService

log = logging.getLogger(__name__)


class BleRuntime:
    def __init__(
        self,
        ble: BLEManager,
        channel_service: ChannelService,
        *,
        conn_factory: Callable[[], sqlite3.Connection],
        scan_duration: float,
    ) -> None:
        self._ble = ble
        self._channel_service = channel_service
        self._conn_factory = conn_factory
        self._scan_duration = scan_duration
        # (address, char_uuid) -> Channel, so make_feed() knows each data_format.
        self._subscribed: dict[tuple[str, str], Channel] = {}

    def activate(self) -> None:
        """Connect every known device and subscribe its display channels."""
        conn = self._conn_factory()
        try:
            for device in devices.list_all(conn):
                try:
                    self._ble.connect(device.address)
                except Exception:
                    log.warning(
                        "connect to %s failed; skipping", device.address, exc_info=True
                    )
                    continue
                for channel in channels.list_by_device(conn, device.id):
                    if channel.type == "display":
                        self.subscribe_channel(device.address, channel)
        finally:
            conn.close()

    def subscribe_channel(self, address: str, channel: Channel) -> None:
        """Subscribe one display channel; each notify opens a short-lived conn."""
        channel_id = channel.id

        def _on_notify(raw: bytes) -> None:
            conn = self._conn_factory()
            try:
                self._channel_service.handle_notify(
                    conn, channel_id=channel_id, raw_bytes=raw
                )
            finally:
                conn.close()

        self._ble.subscribe(address, channel.char_uuid, _on_notify)
        self._subscribed[(address, channel.char_uuid)] = channel

    def make_feed(self) -> Callable[[str, str], bytes | None]:
        """Return a format-aware synthetic reading generator for the mock."""
        state = {"n": 0}

        def feed(address: str, char_uuid: str) -> bytes | None:
            channel = self._subscribed.get((address, char_uuid))
            if channel is None:
                return None
            state["n"] += 1
            value = 25.0 + 5.0 * math.sin(state["n"] / 10.0)
            try:
                return parser.encode(value, channel.data_format)
            except parser.ParseError:
                return None

        return feed
