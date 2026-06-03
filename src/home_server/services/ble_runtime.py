"""Wire BLE notify subscriptions to the channel service, feed the mock, and
keep device connections alive (auto-reconnect with status reporting).

Constructed (inert) by the application factory and stored in app.extensions.
`activate()` connects known devices and subscribes their display channels;
`monitor_start()` runs a background loop that reconnects dropped devices with
exponential backoff and reports status via the injected `on_status` callback.
Side effects (connections, threads) run only from `__main__`; tests drive
`_monitor_tick(now)` directly and stay thread-free.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from home_server.ble import parser
from home_server.ble.interface import BLEManager
from home_server.db import channels, devices
from home_server.db.channels import Channel
from home_server.db.devices import Device
from home_server.services.channel_service import ChannelService

log = logging.getLogger(__name__)

# Reconnect backoff: 1s, 2s, 4s, ... capped at 60s (RPi-Server doc §4.1.3).
_RECONNECT_BASE_S = 1.0
_RECONNECT_FACTOR = 2.0
_RECONNECT_CAP_S = 60.0

STATUS_CONNECTED = "connected"
STATUS_RECONNECTING = "reconnecting"
STATUS_DISCONNECTED = "disconnected"

StatusCallback = Callable[[int, str], None]


def _noop_status(device_id: int, status: str) -> None:
    """Default on_status: no-op (used until create_app wires SocketIO)."""


@dataclass
class _DeviceMonitorState:
    last_status: str | None = None
    backoff_s: float = _RECONNECT_BASE_S
    next_retry_at: float = 0.0


class BleRuntime:
    def __init__(
        self,
        ble: BLEManager,
        channel_service: ChannelService,
        *,
        conn_factory: Callable[[], sqlite3.Connection],
        scan_duration: float,
        on_status: StatusCallback = _noop_status,
    ) -> None:
        self._ble = ble
        self._channel_service = channel_service
        self._conn_factory = conn_factory
        self._scan_duration = scan_duration
        self._on_status = on_status
        # (address, char_uuid) -> Channel, so make_feed() knows each data_format.
        self._subscribed: dict[tuple[str, str], Channel] = {}
        # address -> reconnect bookkeeping.
        self._monitor: dict[str, _DeviceMonitorState] = {}
        self._monitor_thread: threading.Thread | None = None
        self._monitor_stop: threading.Event | None = None

    # ---- Initial bring-up ----

    def activate(self) -> None:
        """Connect every known device and subscribe its display channels."""
        conn = self._conn_factory()
        try:
            for device in devices.list_all(conn):
                self._bring_up_device(conn, device)
        finally:
            conn.close()

    def _bring_up_device(self, conn: sqlite3.Connection, device: Device) -> bool:
        """Connect one device and subscribe its display channels. Returns success."""
        try:
            self._ble.connect(device.address, device.addr_type)
        except Exception:
            log.warning("connect to %s failed", device.address, exc_info=True)
            return False
        # connect() can return without raising while the link is not yet up
        # (the manager may reuse a worker whose connect attempt is still in
        # flight — exactly what a powered-off device produces). is_connected()
        # is the single source of truth: only proceed once it confirms the
        # link, otherwise report failure so the monitor keeps retrying instead
        # of flapping to "connected" and subscribing on a dead link.
        if not self._ble.is_connected(device.address):
            return False
        for channel in channels.list_by_device(conn, device.id):
            if channel.type == "display":
                self.subscribe_channel(device.address, channel)
        return True

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

    # ---- Auto-reconnect monitor ----

    def monitor_start(self, interval_s: float = 1.0) -> None:
        """Run the reconnect monitor in a background daemon thread."""
        if self._monitor_thread is not None:
            return
        stop = threading.Event()

        def _run() -> None:
            while not stop.wait(interval_s):
                try:
                    self._monitor_tick(time.monotonic())
                except Exception:
                    log.exception("BLE monitor tick failed")

        thread = threading.Thread(target=_run, name="ble-monitor", daemon=True)
        self._monitor_stop = stop
        self._monitor_thread = thread
        thread.start()

    def monitor_stop(self) -> None:
        if self._monitor_stop is not None:
            self._monitor_stop.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=2.0)
        self._monitor_thread = None
        self._monitor_stop = None

    def _monitor_tick(self, now: float) -> None:
        """One reconnect pass. Pure w.r.t. time (caller passes `now`)."""
        conn = self._conn_factory()
        try:
            device_list = devices.list_all(conn)
            live = {d.address for d in device_list}
            for addr in list(self._monitor):
                if addr not in live:
                    del self._monitor[addr]
            for device in device_list:
                state = self._monitor.setdefault(device.address, _DeviceMonitorState())
                if self._ble.is_connected(device.address):
                    state.backoff_s = _RECONNECT_BASE_S
                    state.next_retry_at = 0.0
                    self._set_status(device.id, state, STATUS_CONNECTED)
                    continue
                if state.last_status in (None, STATUS_CONNECTED):
                    # Just observed a drop: announce it, schedule first retry.
                    state.backoff_s = _RECONNECT_BASE_S
                    state.next_retry_at = now + state.backoff_s
                    self._set_status(device.id, state, STATUS_DISCONNECTED)
                    continue
                if now >= state.next_retry_at:
                    self._set_status(device.id, state, STATUS_RECONNECTING)
                    if self._bring_up_device(conn, device):
                        state.backoff_s = _RECONNECT_BASE_S
                        state.next_retry_at = 0.0
                        self._set_status(device.id, state, STATUS_CONNECTED)
                    else:
                        state.backoff_s = min(
                            state.backoff_s * _RECONNECT_FACTOR, _RECONNECT_CAP_S
                        )
                        state.next_retry_at = now + state.backoff_s
        finally:
            conn.close()

    def _set_status(
        self, device_id: int, state: _DeviceMonitorState, status: str
    ) -> None:
        if state.last_status != status:
            state.last_status = status
            self._on_status(device_id, status)

    # ---- Mock synthetic feed ----

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
