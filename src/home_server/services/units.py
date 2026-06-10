"""Unit-string helpers for channel display."""

from __future__ import annotations


def parse_enum_unit(unit: str | None) -> dict[int, str] | None:
    """Parse an ``"enum:0=安靜,1=語音,..."`` unit string into an int→label mapping.

    Returns ``None`` when *unit* is ``None`` or does not start with ``"enum:"``.
    Malformed individual pairs (non-integer key, missing ``=``, etc.) are silently
    ignored; the remaining well-formed pairs are still returned.  An empty or
    all-malformed body yields ``{}`` (truthy check fails, so callers may treat
    ``None`` and ``{}`` the same if they wish).

    Examples::

        >>> parse_enum_unit("enum:0=安靜,1=語音,2=拍手")
        {0: '安靜', 1: '語音', 2: '拍手'}
        >>> parse_enum_unit("°C") is None
        True
        >>> parse_enum_unit(None) is None
        True
    """
    if unit is None or not unit.startswith("enum:"):
        return None
    body = unit[len("enum:"):]
    result: dict[int, str] = {}
    for pair in body.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key_str, label = pair.split("=", 1)
        try:
            key = int(key_str.strip())
        except ValueError:
            continue
        result[key] = label
    return result
