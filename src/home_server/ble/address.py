"""BLE address-type helpers (backend-agnostic, importable anywhere).

Kept free of bluepy imports so it works on macOS/dev and in tests. The string
values match bluepy's ``btle.ADDR_TYPE_*`` constants, so a stored value can be
passed straight to ``btle.Peripheral(addr, addrType=...)``.
"""

from __future__ import annotations

ADDR_TYPE_PUBLIC = "public"
ADDR_TYPE_RANDOM = "random"


def infer_addr_type(address: str) -> str:
    """Infer the BLE address type from the most-significant octet.

    BLE static random addresses have the top two bits of the most-significant
    octet set to 0b11. Everything else (public IEEE addresses, and the less
    common resolvable/non-resolvable private forms) is reported as public; the
    scan path supplies the authoritative type when it is available.
    """
    msb = int(address.split(":")[0], 16)
    return ADDR_TYPE_RANDOM if (msb >> 6) == 0b11 else ADDR_TYPE_PUBLIC
