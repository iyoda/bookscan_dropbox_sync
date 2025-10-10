from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Bookscan
    BOOKSCAN_EMAIL: str | None = None
    BOOKSCAN_PASSWORD: str | None = None
    BOOKSCAN_TOTP_SECRET: str | None = None
    BOOKSCAN_BASE_URL: str = "https://www.bookscan.co.jp"
    # デバッグ用: HTTP未実装でもdry-run/開発を進めるためのHTML入力（ファイルパス or 生HTML or http(s)URL）
    BOOKSCAN_DEBUG_HTML_PATH: str | None = None

    # Bookscan HTTPログイン/一覧（任意設定：提供時のみ使用）
    BOOKSCAN_LOGIN_URL: str | None = None
    BOOKSCAN_LOGIN_EMAIL_FIELD: str = "email"
    BOOKSCAN_LOGIN_PASSWORD_FIELD: str = "password"
    BOOKSCAN_LOGIN_TOTP_FIELD: str = "otp"  # 将来のTOTP手動入力/自動化で利用予定

    # 一覧取得URLテンプレート（{page} を含めるとページネーション）
    BOOKSCAN_LIST_URL_TEMPLATE: str | None = None
    BOOKSCAN_LIST_MAX_PAGES: int = 1
    BOOKSCAN_LIST_STOP_ON_EMPTY: bool = True

    # Dropbox（簡易運用：固定アクセストークン）
    DROPBOX_ACCESS_TOKEN: str | None = None

    # Dropbox（推奨：OAuth/Refresh Token運用）
    DROPBOX_APP_KEY: str | None = None
    DROPBOX_APP_SECRET: str | None = None
    DROPBOX_REFRESH_TOKEN: str | None = None
    DROPBOX_TOKEN_ROTATE: bool = True

    # 同期先
    DROPBOX_DEST_ROOT: str = "/Apps/bookscan-sync"

    # 動作パラメータ
    DOWNLOAD_DIR: str = ".cache/downloads"
    STATE_BACKEND: str = "json"  # または "sqlite"
    STATE_PATH: str = ".state/state.json"  # sqliteの場合は .state/state.db
    SYNC_MODE: str = "incremental"  # incremental|full|dry-run
    CONCURRENCY: int = 1
    RATE_LIMIT_QPS: float = 0.5
    BOOKSCAN_RATE_LIMIT_QPS: float | None = None
    DROPBOX_RATE_LIMIT_QPS: float | None = None
    USER_AGENT: str = "bookscan-dropbox-sync/0.1 (+https://github.com/iyoda/bookscan_dropbox_sync)"
    HEADLESS: bool = True
    HTTP_TIMEOUT: int = 60
    FAILURE_LOG_PATH: str = ".logs/failures.jsonl"
    # Dropbox チャンクアップロード設定（M3）
    DROPBOX_CHUNK_UPLOAD_THRESHOLD: int = 8 * 1024 * 1024  # 8MB以上はセッション方式
    DROPBOX_CHUNK_SIZE: int = 8 * 1024 * 1024  # セッション時のチャンクサイズ
    # リトライ設定（M3）
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_BACKOFF_MULTIPLIER: float = 0.1
    RETRY_BACKOFF_MAX: float = 2.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    def validate_for_m1(self, dry_run: bool = False) -> None:
        """
        M1/M4要件の簡易バリデーション:
        - 非ドライラン時は DROPBOX_ACCESS_TOKEN または (DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY) を必須とする
        """
        if not dry_run:
            has_access_token = bool(self.DROPBOX_ACCESS_TOKEN)
            has_refresh_token = bool(self.DROPBOX_REFRESH_TOKEN and self.DROPBOX_APP_KEY)
            if not has_access_token and not has_refresh_token:
                raise ValueError(
                    "Either DROPBOX_ACCESS_TOKEN or (DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY) "
                    "is required for upload (non dry-run)."
                )

    @property
    def is_json_backend(self) -> bool:
        return self.STATE_BACKEND.lower() == "json"


def load_settings() -> Settings:
    return Settings()
