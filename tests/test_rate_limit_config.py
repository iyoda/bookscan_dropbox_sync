from __future__ import annotations

from bds.config import Settings
from bds.bookscan_client import BookscanClient
from bds.dropbox_client import DropboxClient


def test_bookscan_rate_limit_override() -> None:
    s = Settings()
    s.RATE_LIMIT_QPS = 10.0  # fallback
    s.BOOKSCAN_RATE_LIMIT_QPS = 0.5  # override -> min_interval = 2.0s
    c = BookscanClient(s)
    assert abs(c._rl.min_interval - 2.0) < 1e-6


def test_dropbox_rate_limit_override() -> None:
    s = Settings()
    s.RATE_LIMIT_QPS = 10.0  # fallback
    s.DROPBOX_RATE_LIMIT_QPS = 2.0  # override -> min_interval = 0.5s
    # NOTE: DropboxClient.__init__ では Dropbox SDK のインスタンス化は行われないため import だけでOK
    c = DropboxClient(s)
    assert abs(c._rl.min_interval - 0.5) < 1e-6


def test_rate_limit_fallback_when_service_specific_not_set() -> None:
    s = Settings()
    s.RATE_LIMIT_QPS = 4.0  # -> min_interval = 0.25s
    s.BOOKSCAN_RATE_LIMIT_QPS = None
    s.DROPBOX_RATE_LIMIT_QPS = None

    bc = BookscanClient(s)
    dc = DropboxClient(s)

    assert abs(bc._rl.min_interval - 0.25) < 1e-6
    assert abs(dc._rl.min_interval - 0.25) < 1e-6
