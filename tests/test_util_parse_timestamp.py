from __future__ import annotations

import datetime as dt

from bds.util import parse_timestamp


def test_parse_timestamp_iso_z() -> None:
    d = parse_timestamp("2024-08-10T12:00:00Z")
    assert isinstance(d, dt.datetime)
    assert d == dt.datetime(2024, 8, 10, 12, 0, 0)


def test_parse_timestamp_date_only() -> None:
    d = parse_timestamp("2024-08-12")
    assert d == dt.datetime(2024, 8, 12, 0, 0, 0)


def test_parse_timestamp_invalid() -> None:
    assert parse_timestamp("not-a-date") is None
    assert parse_timestamp("") is None  # empty


def test_parse_timestamp_tz_aware_to_utc_naive() -> None:
    # +09:00 の 09:00 は UTC 00:00 と等価 → naive UTC で返る
    d = parse_timestamp("2024-08-10T09:00:00+09:00")
    assert d == dt.datetime(2024, 8, 10, 0, 0, 0)


def test_parse_timestamp_space_separated_datetime() -> None:
    d = parse_timestamp("2024-08-10 12:34:56")
    assert d == dt.datetime(2024, 8, 10, 12, 34, 56)
