"""Convert between raw GATT bytes and Python numeric values.

Each channel stores its ``data_format`` as a string in the DB. This module is
the single place that knows how to encode/decode each format. Adding a new
format means adding one entry to ``_FORMATS``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


class UnknownFormatError(ValueError):
    pass


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class _Format:
    struct_fmt: str
    size: int


# Supported wire formats. Keys are what the DB stores in `channels.data_format`.
_FORMATS: dict[str, _Format] = {
    "uint8":      _Format("<B", 1),
    "int8":       _Format("<b", 1),
    "uint16_le":  _Format("<H", 2),
    "uint16_be":  _Format(">H", 2),
    "int16_le":   _Format("<h", 2),
    "int16_be":   _Format(">h", 2),
    "uint32_le":  _Format("<I", 4),
    "int32_le":   _Format("<i", 4),
    "float32_le": _Format("<f", 4),
    "float32_be": _Format(">f", 4),
}


def supported_formats() -> list[str]:
    return list(_FORMATS.keys())


def decode(data: bytes, fmt: str) -> float:
    """Decode the first ``size`` bytes per ``fmt``. Returns float for uniformity."""
    spec = _FORMATS.get(fmt)
    if spec is None:
        raise UnknownFormatError(f"Unknown data_format: {fmt!r}")
    if len(data) < spec.size:
        raise ParseError(
            f"Need {spec.size} bytes for {fmt}, got {len(data)}: {data.hex()}"
        )
    (value,) = struct.unpack(spec.struct_fmt, data[: spec.size])
    return float(value)


def encode(value: float, fmt: str) -> bytes:
    """Encode ``value`` per ``fmt``. Integer formats truncate via int()."""
    spec = _FORMATS.get(fmt)
    if spec is None:
        raise UnknownFormatError(f"Unknown data_format: {fmt!r}")
    try:
        if fmt.startswith(("uint", "int")):
            return struct.pack(spec.struct_fmt, int(value))
        return struct.pack(spec.struct_fmt, value)
    except struct.error as e:
        raise ParseError(f"Cannot encode {value!r} as {fmt}: {e}") from e
