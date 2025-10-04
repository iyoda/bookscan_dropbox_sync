from __future__ import annotations

from typing import Any, Callable

from tenacity import Retrying, retry_if_exception, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from ..config import Settings


def create_retrying_from_settings(
    settings: Settings,
    failure_store: Any = None,
    fallback_max_attempts: int = 3,
    fallback_backoff_multiplier: float = 0.1,
    fallback_backoff_max: float = 2.0,
) -> Retrying:
    """
    設定から Retrying インスタンスを作成する共通ユーティリティ

    Args:
        settings: Settings インスタンス
        failure_store: FailureStore インスタンス（設定時はclassify_exceptionを使用）
        fallback_max_attempts: 設定がない場合のデフォルト最大試行回数
        fallback_backoff_multiplier: 設定がない場合のデフォルト指数バックオフ乗数
        fallback_backoff_max: 設定がない場合のデフォルト最大待機時間

    Returns:
        設定されたRetryingインスタンス
    """
    # 設定値を取得（フォールバック付き）
    try:
        max_attempts = int(getattr(settings, "RETRY_MAX_ATTEMPTS", fallback_max_attempts))
    except Exception:
        max_attempts = fallback_max_attempts

    try:
        backoff_mult = float(getattr(settings, "RETRY_BACKOFF_MULTIPLIER", fallback_backoff_multiplier))
    except Exception:
        backoff_mult = fallback_backoff_multiplier

    try:
        backoff_max = float(getattr(settings, "RETRY_BACKOFF_MAX", fallback_backoff_max))
    except Exception:
        backoff_max = fallback_backoff_max

    # 値の妥当性チェック
    if backoff_mult <= 0:
        backoff_mult = 0.01
    if backoff_max <= 0:
        backoff_max = 1.0
    max_attempts = max(1, max_attempts)

    # リトライ条件の決定
    if failure_store is not None:
        # FailureStoreがある場合は分類機能を使用
        predicate = retry_if_exception(lambda e: failure_store.classify_exception(e)[1])
    else:
        # ない場合は全例外をリトライ対象とする
        predicate = retry_if_exception_type(Exception)

    return Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(multiplier=backoff_mult, max=backoff_max),
        retry=predicate,
        reraise=True,
    )


def create_simple_retrying(
    max_attempts: int = 5,
    backoff_multiplier: float = 1.0,
    backoff_max: float = 10.0,
) -> Retrying:
    """
    シンプルなRetryingインスタンスを作成（BookscanClient用）

    Args:
        max_attempts: 最大試行回数
        backoff_multiplier: 指数バックオフ乗数
        backoff_max: 最大待機時間

    Returns:
        Retryingインスタンス
    """
    return Retrying(
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(multiplier=backoff_multiplier, max=backoff_max),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )


def call_with_retry(retrying: Retrying, fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """
    Retryingインスタンスを使って関数を実行

    Args:
        retrying: Retryingインスタンス
        fn: 実行する関数
        *args: 関数の位置引数
        **kwargs: 関数のキーワード引数

    Returns:
        関数の実行結果
    """
    for attempt in retrying:
        with attempt:
            return fn(*args, **kwargs)