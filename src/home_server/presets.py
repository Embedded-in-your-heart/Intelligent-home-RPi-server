"""Channel preset catalog loaded from a JSON file.

A preset bundles the technical fields of a BLE channel (char_uuid, type,
data_format, unit) behind a human-friendly label, so the "add channel" UI can
offer a single dropdown instead of asking the user to type a UUID/unit and pick
a type/format. The catalog lives in a JSON file (``Config.channel_presets_path``)
so it can be edited without code changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from home_server.ble import parser
from home_server.db.channels import Channel, ChannelType

_VALID_TYPES: tuple[ChannelType, ...] = ("controller", "display")


class PresetError(ValueError):
    pass


@dataclass(frozen=True)
class ChannelPreset:
    label: str
    char_uuid: str
    type: ChannelType
    data_format: str
    unit: str | None


def available_presets(
    presets: list[ChannelPreset], existing: list[Channel]
) -> list[ChannelPreset]:
    """Presets not yet used on a device (each char_uuid can be added once)."""
    used = {c.char_uuid for c in existing}
    return [p for p in presets if p.char_uuid not in used]


def load_presets(path: Path) -> list[ChannelPreset]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise PresetError(f"cannot read channel presets file {path}: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PresetError(f"invalid JSON in {path}: {e}") from e
    if not isinstance(data, list):
        raise PresetError(f"{path}: top level must be a JSON array")

    presets: list[ChannelPreset] = []
    seen_labels: set[str] = set()
    seen_uuids: set[str] = set()
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise PresetError(f"{path}[{i}]: entry must be an object")
        label = entry.get("label")
        char_uuid = entry.get("char_uuid")
        ctype = entry.get("type")
        data_format = entry.get("data_format")
        unit = entry.get("unit")
        if not isinstance(label, str) or not label:
            raise PresetError(f"{path}[{i}]: 'label' must be a non-empty string")
        if not isinstance(char_uuid, str) or not char_uuid:
            raise PresetError(f"{path}[{i}]: 'char_uuid' must be a non-empty string")
        if ctype not in _VALID_TYPES:
            raise PresetError(
                f"{path}[{i}]: 'type' must be one of {_VALID_TYPES}, got {ctype!r}"
            )
        if data_format not in parser.supported_formats():
            raise PresetError(f"{path}[{i}]: unknown 'data_format' {data_format!r}")
        if unit is not None and not isinstance(unit, str):
            raise PresetError(f"{path}[{i}]: 'unit' must be a string or null")
        if label in seen_labels:
            raise PresetError(f"{path}[{i}]: duplicate label {label!r}")
        if char_uuid in seen_uuids:
            raise PresetError(f"{path}[{i}]: duplicate char_uuid {char_uuid!r}")
        seen_labels.add(label)
        seen_uuids.add(char_uuid)
        presets.append(
            ChannelPreset(
                label=label,
                char_uuid=char_uuid,
                type=ctype,
                data_format=data_format,
                unit=unit,
            )
        )
    return presets
