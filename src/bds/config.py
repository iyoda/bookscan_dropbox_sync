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
    STATE_BACKEND: str = "json"  # または "sqlite"
    STATE_PATH: str = ".state/state.json"  # sqliteの場合は .state/state.db
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

    def validate_for_m1(self, dry_run: bool = False) -> None:
        """
        M1要件の簡易バリデーション:
        - 非ドライラン時は DROPBOX_ACCESS_TOKEN を必須とする
        """
        if not dry_run and not self.DROPBOX_ACCESS_TOKEN:
            raise ValueError("DROPBOX_ACCESS_TOKEN is required for upload (non dry-run).")

    @property
    def is_json_backend(self) -> bool:
        return self.STATE_BACKEND.lower() == "json"


def load_settings() -> Settings:
    return Settings()
