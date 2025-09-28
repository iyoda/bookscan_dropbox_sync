from __future__ import annotations

import string

from bds.util import safe_filename


def test_safe_filename_replaces_forbidden_chars() -> None:
    forbidden = '/\\:*?"<>|'
    name = f"abc{forbidden}def"
    out = safe_filename(name)
    # 置換が行われ、禁則文字が含まれないこと
    for ch in forbidden:
        assert ch not in out
    assert out == "abc_________def"  # 9文字が "_" へ


def test_safe_filename_collapses_spaces_and_strips() -> None:
    name = "  Hello   World   "
    out = safe_filename(name)
    assert out == "Hello World"


def test_safe_filename_truncates_long_names() -> None:
    long = "A" * 200
    out = safe_filename(long, max_length=150)
    assert len(out) == 150
    assert out == "A" * 150


def test_safe_filename_allows_typical_chars() -> None:
    allowed_sample = "().-_ " + string.ascii_letters + string.digits
    # 許容文字はそのまま
    out = safe_filename(allowed_sample)
    assert out == allowed_sample
