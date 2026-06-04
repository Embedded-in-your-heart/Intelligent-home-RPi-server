import json
from pathlib import Path

import pytest

from home_server.presets import ChannelPreset, PresetError, load_presets


def _write(tmp_path: Path, data: object) -> Path:
    p = tmp_path / "presets.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_valid_presets(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            {
                "label": "Temp",
                "char_uuid": "uuid-temp",
                "type": "display",
                "data_format": "float32_le",
                "unit": "°C",
            },
            {
                "label": "LED",
                "char_uuid": "uuid-led",
                "type": "controller",
                "data_format": "uint8",
            },
        ],
    )
    presets = load_presets(path)
    assert presets == [
        ChannelPreset("Temp", "uuid-temp", "display", "float32_le", "°C"),
        ChannelPreset("LED", "uuid-led", "controller", "uint8", None),
    ]


def test_missing_unit_becomes_none(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [{"label": "X", "char_uuid": "u", "type": "display", "data_format": "uint8"}],
    )
    assert load_presets(path)[0].unit is None


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PresetError):
        load_presets(tmp_path / "nope.json")


def test_invalid_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "presets.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(PresetError):
        load_presets(p)


def test_top_level_not_list_raises(tmp_path: Path) -> None:
    with pytest.raises(PresetError):
        load_presets(_write(tmp_path, {"label": "X"}))


def test_bad_type_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [{"label": "X", "char_uuid": "u", "type": "sensor", "data_format": "uint8"}],
    )
    with pytest.raises(PresetError):
        load_presets(path)


def test_unknown_data_format_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [{"label": "X", "char_uuid": "u", "type": "display", "data_format": "bogus"}],
    )
    with pytest.raises(PresetError):
        load_presets(path)


def test_empty_label_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [{"label": "", "char_uuid": "u", "type": "display", "data_format": "uint8"}],
    )
    with pytest.raises(PresetError):
        load_presets(path)


def test_duplicate_label_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            {"label": "X", "char_uuid": "u1", "type": "display", "data_format": "uint8"},
            {"label": "X", "char_uuid": "u2", "type": "display", "data_format": "uint8"},
        ],
    )
    with pytest.raises(PresetError):
        load_presets(path)


def test_duplicate_char_uuid_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        [
            {"label": "A", "char_uuid": "u", "type": "display", "data_format": "uint8"},
            {"label": "B", "char_uuid": "u", "type": "display", "data_format": "uint8"},
        ],
    )
    with pytest.raises(PresetError):
        load_presets(path)


def test_empty_list_is_valid(tmp_path: Path) -> None:
    assert load_presets(_write(tmp_path, [])) == []


def test_shipped_catalog_loads() -> None:
    repo_root = Path(__file__).parent.parent
    presets = load_presets(repo_root / "data" / "channel_presets.json")
    assert len(presets) == 9
    labels = {p.label for p in presets}
    assert "溫度 (°C)" in labels
