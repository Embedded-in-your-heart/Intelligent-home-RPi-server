import math

import pytest

from home_server.ble import parser


class TestDecode:
    def test_uint8(self) -> None:
        assert parser.decode(b"\x2a", "uint8") == 42.0

    def test_int8_negative(self) -> None:
        assert parser.decode(b"\xff", "int8") == -1.0

    def test_uint16_le(self) -> None:
        assert parser.decode(b"\x34\x12", "uint16_le") == 0x1234

    def test_uint16_be(self) -> None:
        assert parser.decode(b"\x12\x34", "uint16_be") == 0x1234

    def test_int16_le_negative(self) -> None:
        assert parser.decode(b"\xff\xff", "int16_le") == -1.0

    def test_float32_le(self) -> None:
        # 25.5 °C as little-endian float32
        data = bytes.fromhex("0000cc41")
        assert math.isclose(parser.decode(data, "float32_le"), 25.5)

    def test_extra_bytes_ignored(self) -> None:
        assert parser.decode(b"\x2a\xff\xff", "uint8") == 42.0

    def test_too_few_bytes(self) -> None:
        with pytest.raises(parser.ParseError):
            parser.decode(b"\x01", "uint16_le")

    def test_unknown_format(self) -> None:
        with pytest.raises(parser.UnknownFormatError):
            parser.decode(b"\x00", "complex64")


class TestEncode:
    def test_uint8_round_trip(self) -> None:
        assert parser.decode(parser.encode(7, "uint8"), "uint8") == 7.0

    def test_uint16_le(self) -> None:
        assert parser.encode(0x1234, "uint16_le") == b"\x34\x12"

    def test_float32_le_round_trip(self) -> None:
        encoded = parser.encode(3.14, "float32_le")
        assert math.isclose(parser.decode(encoded, "float32_le"), 3.14, rel_tol=1e-6)

    def test_overflow_raises(self) -> None:
        with pytest.raises(parser.ParseError):
            parser.encode(500, "uint8")

    def test_unknown_format(self) -> None:
        with pytest.raises(parser.UnknownFormatError):
            parser.encode(1, "foo")


def test_supported_formats_nonempty() -> None:
    fmts = parser.supported_formats()
    assert "uint8" in fmts
    assert "float32_le" in fmts
