"""Tests for home_server.services.units.parse_enum_unit."""

from home_server.services.units import parse_enum_unit


def test_valid_enum_unit() -> None:
    result = parse_enum_unit("enum:0=安靜,1=語音,2=拍手,3=警報,4=其他")
    assert result == {0: "安靜", 1: "語音", 2: "拍手", 3: "警報", 4: "其他"}


def test_none_input_returns_none() -> None:
    assert parse_enum_unit(None) is None


def test_non_enum_unit_returns_none() -> None:
    assert parse_enum_unit("°C") is None
    assert parse_enum_unit("0/1") is None
    assert parse_enum_unit("") is None


def test_malformed_pairs_are_skipped() -> None:
    # "bad" has no "=", "x=label" has non-integer key — both skipped
    result = parse_enum_unit("enum:0=安靜,bad,x=label,1=語音")
    assert result == {0: "安靜", 1: "語音"}


def test_empty_body_returns_empty_dict() -> None:
    result = parse_enum_unit("enum:")
    assert result == {}


def test_single_pair() -> None:
    result = parse_enum_unit("enum:0=安靜")
    assert result == {0: "安靜"}


def test_whitespace_around_keys_and_labels_is_stripped() -> None:
    # Hand-typed unit strings often carry stray spaces; they must not leak
    # into the badge text.
    result = parse_enum_unit("enum:0= 安靜 , 1 =語音")
    assert result == {0: "安靜", 1: "語音"}


def test_value_with_equals_sign() -> None:
    # Only the first "=" is used as the separator; the rest belong to the label.
    result = parse_enum_unit("enum:0=a=b")
    assert result == {0: "a=b"}
