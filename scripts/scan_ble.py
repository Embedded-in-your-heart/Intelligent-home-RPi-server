"""Standalone BLE scanner for RPi verification.

Run on RPi:
    uv run python scripts/scan_ble.py [duration_seconds]
"""

from __future__ import annotations

import sys

from home_server.ble.bluepy_manager import BluepyManager
from home_server.core.logging import setup_logging


def main() -> None:
    setup_logging("INFO")
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    mgr = BluepyManager()
    print(f"Scanning for {duration}s...")
    devices = mgr.start_scan(duration)
    if not devices:
        print("No devices found.")
        return
    for d in devices:
        name = d.name or "<no name>"
        print(f"  {d.address}  rssi={d.rssi:>4d}  {name}")
    print(f"Total: {len(devices)}")


if __name__ == "__main__":
    main()
