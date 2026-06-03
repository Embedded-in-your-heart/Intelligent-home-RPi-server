import pytest

from home_server.ble.address import (
    ADDR_TYPE_PUBLIC,
    ADDR_TYPE_RANDOM,
    infer_addr_type,
)


@pytest.mark.parametrize(
    "address,expected",
    [
        ("f6:8c:f2:d3:ea:e7", ADDR_TYPE_RANDOM),  # 0xf6 = 0b11110110 -> top2=11
        ("c0:00:00:00:00:00", ADDR_TYPE_RANDOM),  # 0xc0 = 0b11000000 -> top2=11
        ("ff:ff:ff:ff:ff:ff", ADDR_TYPE_RANDOM),  # 0xff -> top2=11
        ("bf:00:00:00:00:00", ADDR_TYPE_PUBLIC),  # 0xbf = 0b10111111 -> top2=10
        ("aa:bb:cc:dd:ee:ff", ADDR_TYPE_PUBLIC),  # 0xaa = 0b10101010 -> top2=10
        ("00:11:22:33:44:55", ADDR_TYPE_PUBLIC),  # 0x00 -> top2=00
    ],
)
def test_infer_addr_type(address: str, expected: str) -> None:
    assert infer_addr_type(address) == expected
