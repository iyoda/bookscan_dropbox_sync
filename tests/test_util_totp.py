from __future__ import annotations

from bds.util import totp


def test_totp_rfc_vectors_sha1_8digits() -> None:
    # RFC 6238 test secret for SHA-1 (base32 for '12345678901234567890')
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"

    # Time = 59 -> 94287082 (TOTP with step=30, digits=8)
    assert totp(secret, t=59, step=30, digits=8) == "94287082"

    # Time = 1111111109 -> 07081804
    assert totp(secret, t=1111111109, step=30, digits=8) == "07081804"

    # Time = 2000000000 -> 69279037
    assert totp(secret, t=2000000000, step=30, digits=8) == "69279037"

