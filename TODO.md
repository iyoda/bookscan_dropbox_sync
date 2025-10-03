# TODO: bookscan_dropbox_sync

本プロジェクトの実装計画とタスク一覧。優先順位とマイルストーン単位で分割し、進捗を随時更新する。

## マイルストーン概要

- M0 設計・土台（このREADME/TODO、開発基盤）: 最低限のプロジェクト構成と品質基盤
- M1 最小同期（MVP）: 固定Dropboxアクセストークン、JSON State、requestsのみでBookscan→Dropboxの一方向同期
- M2 実用CLI: フィルタ/ドライラン/詳細ログ、SQLite State、命名規則、重複回避
- M3 信頼性/スケール: 並行処理、指数バックオフ、チャンクアップロード、堅牢化
- M4 認証/自動化強化: Dropbox OAuth Refresh Token運用、Playwrightフォールバック（必要時）
- M5 配布/運用: CI/CD、パッケージ化、スケジューリング運用ガイド

---

## M0 設計・土台

- [x] 設計初版（README.md）を作成
- [x] 実装タスク（TODO.md）を作成
- [x] Pythonプロジェクト初期化
  - [x] pyproject.toml または requirements.txt 追加
  - [x] 仮想環境手順（READMEに記載）
  - [x] .gitignore（.env, .state, .cache, .logs, __pycache__ 等）
- [x] 開発基盤
  - [x] Linter/Formatter（ruff, black）
  - [x] 型チェック（mypy）
  - [x] pre-commit（整形・静的解析の自動化）
  - [x] テスト基盤（pytest, coverage）
- [x] ひな型作成（空実装）
  - [x] src/bds/__init__.py
  - [x] src/bds/cli.py
  - [x] src/bds/config.py
  - [x] src/bds/bookscan_client.py
  - [x] src/bds/dropbox_client.py
  - [x] src/bds/state_store.py
  - [x] src/bds/sync_planner.py
  - [x] src/bds/transfer.py
  - [x] src/bds/util/__init__.py
- [x] .env.example 作成（READMEの環境変数を反映）

推奨依存（検討中）
- runtime: requests, beautifulsoup4, dropbox, typer, pydantic, python-dotenv, tenacity
- optional: pyotp（TOTP）, playwright（フォールバック）, aiohttp（将来の並列化）, tqdm（進捗）
- dev: pytest, pytest-cov, ruff, black, mypy, vcrpy（HTTP録画, 任意）

---

## M1 最小同期（MVP）

- [x] Config/環境変数読込
  - [x] pydantic/Envで設定を読み込む
  - [x] 必須/任意のバリデーション（例: DROPBOX_ACCESS_TOKEN 必須 in MVP）
- [x] BookscanClient（requests版）
  - [x] ログイン（メール/パスワード、Cookie保持）
  - [x] ダウンロード可能一覧のスクレイピング（ページネーション対応の最低限）
  - [x] アイテムメタ（タイトル/拡張子/pdf URL/更新日/サイズの取得可能な範囲）
  - [x] 単体テスト（HTML Fixtureでのパーステスト）
  - [x] デバッグHTMLフォールバック（BOOKSCAN_DEBUG_HTML_PATHでlist/download可）
- [x] DropboxClient（固定アクセストークン）
  - [x] 単純なファイルアップロード（小サイズ前提）
  - [x] フォルダ作成・存在チェック
  - [x] メタデータ取得（同名判定の基礎）
- [x] StateStore（JSON版）
  - [x] スキーマ定義（book_id, updated_at, size, hash, dropbox_path 等）
  - [x] 読み書き・初期化
- [x] SyncPlanner
  - [x] Stateとの差分計算（新規/更新のみ抽出）
  - [x] 命名規則（安全なファイル名への正規化の初版）
- [x] Transfer（最小）
  - [x] ダウンロード→一時フォルダ→Dropboxアップロード
  - [x] 成功時にState更新
- [x] CLI
  - [x] `sync` サブコマンド
  - [x] `--dry-run`（アップロードせず計画のみ表示）
  - [x] ログ（INFO/ERROR）

受け入れ条件（M1）
- [x] `python -m bds.cli sync --dry-run` で予定アップロードの一覧が出る
- [x] `python -m bds.cli sync` で新規PDFがDropboxに1件以上アップロードされる
- [x] 同期済みファイルは再アップロードされない（簡易増分）

---

## M2 実用CLI

- [x] StateStore（SQLite対応）
  - [x] SQLite実装・移行パス
  - [x] インデックス/整合性制御
- [x] Dropbox重複回避
  - [x] 同名ファイルのハッシュ/サイズ照合
  - [x] 衝突時のリネームポリシー（例: (dup), (v2)）
- [x] フィルタ機能
  - [x] `--since`（日付）
  - [x] 拡張子/サイズ/キーワード除外
- [x] ログ強化
  - [x] JSONログオプション
  - [x] ファイル出力（.logs）
- [x] CLI拡張
  - [x] `list` サブコマンド（取得一覧/State表示）
  - [x] 失敗時の終了コード整理
    - [x] 実行時エラー（初期化/転送失敗）で code=1 を返す
    - [x] 設定エラー時（非ドライラン時のDROPBOX_ACCESS_TOKEN不足）で code=2 を返す

- [x] Bookscan HTML 直解析強化（変換不要での開発を支援）
  - [x] showbook.php から id/title/pdf_url を抽出
  - [x] bookshelf_all_list.php から showbook リンク抽出
  - [x] `/download.php?...` のルート相対URLを `BOOKSCAN_BASE_URL` と結合して取得

受け入れ条件（M2）
- [x] `--since` 等のフィルタが機能し、結果がドライランに反映
- [x] 同名重複時の期待どおりの挙動（上書きしない/リネーム）

---

## M3 信頼性/スケール

- [x] 転送の堅牢化
  - [x] tenacityで指数バックオフ＋jitter
  - [x] チャンクアップロード（Dropbox SDK）
  - [x] DL/ULの整合性チェック（サイズ/ハッシュ）
- [x] 並行実行
  - [x] スレッド/asyncいずれかで並列ダウンロード/アップロード
  - [x] レート制限/帯域制御（QPS/同時数）
- [x] エラーカタログ化
  - [x] リトライ可能/不可の分類（FailureStore._classify_exception）
  - [x] 永続失敗の記録（JSONL/SQLite・FailureStore）
  - [x] 失敗の再評価/再試行ポリシー

受け入れ条件（M3）
- [ ] 429/5xx が一定割合で発生しても全体が成功（リトライにより回復）
- [ ] 大量ファイル（数百件）での完走実績

---

## M4 認証/自動化強化

- [ ] Dropbox OAuth（推奨運用）
  - [ ] OAuth 2.0 Authorization Code + PKCE 実装（client_secret不要）
  - [ ] token_access_type=offline で refresh_token を取得
  - [ ] スコープ定義: files.metadata.read/write, files.content.read/write
  - [ ] ローカルリダイレクトURI（http://localhost:53682/callback）ハンドラ
  - [ ] refresh_token の安全な保存（.env もしくはKeychain/1Password; 将来切替可能）
  - [ ] access_token 自動更新（refresh）と失効時の再認可ハンドリング
  - [x] `login dropbox` コマンド（ブラウザ起動/手動コード入力フォールバック）
  - [x] `logout dropbox` コマンド（/2/auth/token/revoke）
  - [ ] DROPBOX_TOKEN_ROTATE フラグの運用/テスト
- [x] Bookscan認証（実装完了）
  - [x] 実際のBookscanサイトへのログイン対応
  - [x] メール/パスワード認証（BOOKSCAN_EMAIL, BOOKSCAN_PASSWORD）
  - [x] セッション維持（Cookieベース）
  - [x] bookshelf_all_list.phpからの書籍一覧取得
  - [x] showbook.phpページのパース対応
  - [x] TOTP自動生成対応（環境変数 BOOKSCAN_TOTP_SECRET）
  - [x] list_downloadables()のバグ修正（_parse_any_html使用）
- [ ] Playwrightフォールバック（必要時）
  - [ ] Bot検知/CAPTCHA時のみ切替
  - [ ] Cookie移行/セッション維持

受け入れ条件（M4）
- [ ] ローカルブラウザで認可→refresh_token取得が安定（token_access_type=offline, PKCE）
- [ ] refresh_tokenからaccess_tokenの自動更新で長期稼働が安定（期限切れ時も復旧）
- [ ] `login dropbox`/`logout dropbox` の操作で認可/失効ができる
- [x] 2FA環境でもログイン～同期が可能（TOTP対応済み）
- [x] 実際のBookscanサイトへのログインと書籍一覧取得が動作

---

## M5 配布/運用

- [x] CI（GitHub Actions）
  - [x] lint / typecheck / test / coverage
  - [x] キャッシュ活用
- [ ] リリース
  - [ ] バージョニング/タグ
  - [ ] CHANGELOG
  - [ ] pipx配布（任意）
- [ ] 運用
  - [ ] cron/launchd 手順検証
  - [ ] ログローテーション/監視（任意）

---

## テスト計画

- [x] 単体テスト（パーサ/命名/差分計算）
- [x] 結合テスト（Bookscan→Transfer→Dropboxをモックで）
- [ ] 疑似E2E（録画済みHTML/HTTPでの再現、VCR.py活用）
- [ ] 負荷/回復テスト（429/5xx注入、ネットワーク断）
- [ ] カバレッジ目標（例: 80%）

---

## セキュリティ/コンプライアンス

- [x] 機微情報をログ出力しない（マスク）
- [x] .env/.state/.cache/.logs をgitignore
- [x] UAとレート制限の明示（規約順守）
- [x] 依存脆弱性チェック（pip-audit 等）

---

## ドキュメント

- [x] README初版
- [x] TODO初版
- [x] .env.example 整備
- [x] 開発用デバッグ手順（BOOKSCAN_DEBUG_HTML_PATH）追記
- [x] Dropbox OAuth手順（PKCE + Refresh Token）追記
- [x] RETRY_* 設定の説明
- [x] 使い方（各サブコマンド）詳細
- [x] トラブルシュートの更新（CAPTCHA/TOTP/OAuth）
- [x] 貢献ガイド（任意）

---

## バックログ（将来候補）

- [ ] 他ストレージ（GDrive/OneDrive/S3）
- [ ] Web UI / 進捗可視化
- [ ] Slack/メール通知
- [ ] Docker化、CIでのE2E
- [ ] Keychain/1Password CLI連携
