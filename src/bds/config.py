from __future__ import annotations

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Bookscan
    BOOKSCAN_EMAIL: Optional[str] = None
    BOOKSCAN_PASSWORD: Optional[str] = None
    BOOKSCAN_TOTP_SECRET: Optional[str] = None
    BOOKSCAN_BASE_URL: str = "https://www.bookscan.co.jp"

    # Dropbox（簡易運用：固定アクセストークン）
    DROPBOX_ACCESS_TOKEN: Optional[str] = None

    # Dropbox（推奨：OAuth/Refresh Token運用）
    DROPBOX_APP_KEY: Optional[str] = None
    DROPBOX_APP_SECRET: Optional[str] = None
    DROPBOX_REFRESH_TOKEN: Optional[str] = None
    DROPBOX_TOKEN_ROTATE: bool = True

    # 同期先
    DROPBOX_DEST_ROOT: str = "/Apps/bookscan-sync"

    # 動作パラメータ
    DOWNLOAD_DIR: str = ".cache/downloads"
    STATE_BACKEND: str = "sqlite"  # または "json"
    STATE_PATH: str = ".state/state.db"  # jsonの場合は .state/state.json
    SYNC_MODE: str = "incremental"  # incremental|full|dry-run
    CONCURRENCY: int = 2
    RATE_LIMIT_QPS: float = 0.5
    USER_AGENT: str = "bookscan-dropbox-sync/0.1 (+https://github.com/iyoda/bookscan_dropbox_sync)"
    HEADLESS: bool = True
    HTTP_TIMEOUT: int = 60

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )


def load_settings() -> Settings:
    return Settings()
