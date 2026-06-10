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

import contextlib
import logging
import math
import sqlite3
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from home_server.ble import parser
from home_server.ble.interface import BLEManager
from home_server.core.periodic import PeriodicWorker
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
    # Whether display channels are subscribed for the current connection. Reset
    # on every observed drop so the next connect re-subscribes.
    subscribed: bool = False


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
        self._monitor_worker: PeriodicWorker | None = None
        # Interval the monitor was last started with, so scan_window() can
        # restore it after temporarily stopping the monitor for a scan.
        self._monitor_interval_s: float = 1.0

    # ---- Initial bring-up ----

    def activate(self) -> None:
        """Connect every known device and subscribe its display channels.

        Synchronous one-shot bring-up at startup. Devices brought up here seed
        the monitor with ``subscribed=True`` so its first tick reports them
        connected without re-subscribing; failures are left for the monitor to
        retry over the non-blocking reconnect path.
        """
        conn = self._conn_factory()
        try:
            for device in devices.list_all(conn):
                if self._bring_up_device(conn, device):
                    self._monitor[device.address] = _DeviceMonitorState(subscribed=True)
        finally:
            conn.close()

    def _bring_up_device(self, conn: sqlite3.Connection, device: Device) -> bool:
        """Connect one device (blocking) and subscribe its display channels.
        Returns whether the link came up."""
        try:
            self._ble.connect(device.address, device.addr_type)
        except Exception:
            log.warning("connect to %s failed", device.address, exc_info=True)
            return False
        # connect() blocks until linked or raises, but is_connected() stays the
        # authoritative guard against subscribing on a half-open link.
        if not self._ble.is_connected(device.address):
            return False
        self._subscribe_display_channels(conn, device)
        return True

    def _subscribe_display_channels(
        self, conn: sqlite3.Connection, device: Device
    ) -> None:
        for channel in channels.list_by_device(conn, device.id):
            if channel.type == "display":
                self.subscribe_channel(device.address, channel)

    def on_channel_added(self, device: Device, channel: Channel) -> None:
        """Subscribe a freshly created display channel on an already-live link.

        Without this, a channel added while the device is connected only gets
        subscribed after the link drops and the monitor re-subscribes (i.e.
        after a device reset).
        """
        if channel.type != "display":
            return
        if not self._ble.is_connected(device.address):
            return
        self.subscribe_channel(device.address, channel)

    def on_channel_removed(self, device: Device, channel: Channel) -> None:
        """Tear down the BLE notify subscription for a deleted display channel.

        Removes the ``(address, char_uuid)`` entry from ``_subscribed``
        unconditionally so the mock feed stops delivering data and the notify
        closure can be garbage-collected.  The BLE-level ``unsubscribe`` call is
        only issued when the link is up; the real bluepy backend raises
        ``ConnectionError`` via ``_require_worker`` if the device is not
        connected, so we guard with ``is_connected`` — mirroring
        ``on_channel_added``.
        """
        if channel.type != "display":
            return
        self._subscribed.pop((device.address, channel.char_uuid), None)
        if self._ble.is_connected(device.address):
            self._ble.unsubscribe(device.address, channel.char_uuid)

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
        if self._monitor_worker is not None:
            return
        self._monitor_interval_s = interval_s
        self._monitor_worker = PeriodicWorker(
            lambda: self._monitor_tick(time.monotonic()),
            interval_s=interval_s,
            name="ble-monitor",
        )
        self._monitor_worker.start()

    def monitor_stop(self) -> None:
        if self._monitor_worker is not None:
            self._monitor_worker.stop()
            self._monitor_worker = None

    # ---- Scan coordination ----

    @contextlib.contextmanager
    def scan_window(self) -> Iterator[None]:
        """Free the BLE adapter for a scan, then restore normal operation.

        bluepy cannot reliably run a ``Scanner`` on the same hci adapter while
        peripherals are connected: the scan's mgmt ``scanend`` collides with a
        disconnect event and raises ``BTLEDisconnectError``. So for the scan
        body we stop the reconnect monitor and drop every live link; on exit we
        restart the monitor (only if it was running), which reconnects and
        re-subscribes each device over the next few ticks.
        """
        was_running = self._monitor_worker is not None
        self.monitor_stop()
        self._disconnect_all()
        try:
            yield
        finally:
            if was_running:
                self.monitor_start(self._monitor_interval_s)

    def _disconnect_all(self) -> None:
        conn = self._conn_factory()
        try:
            addresses = [d.address for d in devices.list_all(conn)]
        finally:
            conn.close()
        for address in addresses:
            if self._ble.is_connected(address):
                self._ble.disconnect(address)

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
                    self._on_connected(conn, device, state)
                    continue
                # Link is down: the next connect must re-subscribe.
                state.subscribed = False
                if state.last_status in (None, STATUS_CONNECTED):
                    # Just observed a drop: record last-online moment (only if
                    # it was truly connected, not None at startup), then announce.
                    if state.last_status == STATUS_CONNECTED:
                        devices.touch_last_connected(conn, device.id)
                    state.backoff_s = _RECONNECT_BASE_S
                    state.next_retry_at = now + state.backoff_s
                    self._set_status(device.id, state, STATUS_DISCONNECTED)
                    continue
                if now >= state.next_retry_at:
                    self._set_status(device.id, state, STATUS_RECONNECTING)
                    # Non-blocking: kick the attempt and re-check. A synchronous
                    # backend links up within this tick; an async one (bluepy)
                    # links up on a later tick, where the branch above subscribes.
                    self._ble.ensure_connecting(device.address, device.addr_type)
                    if self._ble.is_connected(device.address):
                        self._on_connected(conn, device, state)
                    else:
                        state.backoff_s = min(
                            state.backoff_s * _RECONNECT_FACTOR, _RECONNECT_CAP_S
                        )
                        state.next_retry_at = now + state.backoff_s
        finally:
            conn.close()

    def _on_connected(
        self, conn: sqlite3.Connection, device: Device, state: _DeviceMonitorState
    ) -> None:
        """A device is (or just became) connected: subscribe its display
        channels once per connection, reset backoff, report connected."""
        if not state.subscribed:
            self._subscribe_display_channels(conn, device)
            state.subscribed = True
        state.backoff_s = _RECONNECT_BASE_S
        state.next_retry_at = 0.0
        # Record last-online moment on the transition into connected.
        if state.last_status != STATUS_CONNECTED:
            devices.touch_last_connected(conn, device.id)
        self._set_status(device.id, state, STATUS_CONNECTED)

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
