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
- [ ] BookscanClient（requests版）
  - [ ] ログイン（メール/パスワード、Cookie保持）
  - [ ] ダウンロード可能一覧のスクレイピング（ページネーション対応の最低限）
  - [x] アイテムメタ（タイトル/拡張子/pdf URL/更新日/サイズの取得可能な範囲）
  - [x] 単体テスト（HTML Fixtureでのパーステスト）
- [ ] DropboxClient（固定アクセストークン）
  - [x] 単純なファイルアップロード（小サイズ前提）
  - [x] フォルダ作成・存在チェック
  - [x] メタデータ取得（同名判定の基礎）
- [ ] StateStore（JSON版）
  - [x] スキーマ定義（book_id, updated_at, size, hash, dropbox_path 等）
  - [x] 読み書き・初期化
- [ ] SyncPlanner
  - [x] Stateとの差分計算（新規/更新のみ抽出）
  - [x] 命名規則（安全なファイル名への正規化の初版）
- [ ] Transfer（最小）
  - [x] ダウンロード→一時フォルダ→Dropboxアップロード
  - [x] 成功時にState更新
- [ ] CLI
  - [x] `sync` サブコマンド
  - [x] `--dry-run`（アップロードせず計画のみ表示）
  - [x] ログ（INFO/ERROR）

受け入れ条件（M1）
- [x] `python -m bds.cli sync --dry-run` で予定アップロードの一覧が出る
- [ ] `python -m bds.cli sync` で新規PDFがDropboxに1件以上アップロードされる
- [ ] 同期済みファイルは再アップロードされない（簡易増分）

---

## M2 実用CLI

- [ ] StateStore（SQLite対応）
  - [ ] SQLite実装・移行パス
  - [ ] インデックス/整合性制御
- [ ] Dropbox重複回避
  - [ ] 同名ファイルのハッシュ/サイズ照合
  - [ ] 衝突時のリネームポリシー（例: (dup), (v2)）
- [ ] フィルタ機能
  - [ ] `--since`（日付）
  - [ ] 拡張子/サイズ/キーワード除外
- [ ] ログ強化
  - [ ] JSONログオプション
  - [ ] ファイル出力（.logs）
- [ ] CLI拡張
  - [ ] `list` サブコマンド（取得一覧/State表示）
  - [ ] 失敗時の終了コード整理

受け入れ条件（M2）
- [ ] `--since` 等のフィルタが機能し、結果がドライランに反映
- [ ] 同名重複時の期待どおりの挙動（上書きしない/リネーム）

---

## M3 信頼性/スケール

- [ ] 転送の堅牢化
  - [ ] tenacityで指数バックオフ＋jitter
  - [ ] チャンクアップロード（Dropbox SDK）
  - [ ] DL/ULの整合性チェック（サイズ/ハッシュ）
- [ ] 並行実行
  - [ ] スレッド/asyncいずれかで並列ダウンロード/アップロード
  - [ ] レート制限/帯域制御（QPS/同時数）
- [ ] エラーカタログ化
  - [ ] リトライ可能/不可の分類
  - [ ] 永続失敗の記録と再評価

受け入れ条件（M3）
- [ ] 429/5xx が一定割合で発生しても全体が成功（リトライにより回復）
- [ ] 大量ファイル（数百件）での完走実績

---

## M4 認証/自動化強化

- [ ] Dropbox OAuth（推奨運用）
  - [ ] Refresh Tokenフロー（短期アクセストークン自動更新）
  - [ ] `login dropbox` コマンド（将来: ブラウザ起動）
- [ ] Bookscan 2FA/TOTP
  - [ ] pyotp対応（環境変数 or 対話入力）
- [ ] Playwrightフォールバック（必要時）
  - [ ] Bot検知/CAPTCHA時のみ切替
  - [ ] Cookie移行/セッション維持

受け入れ条件（M4）
- [ ] 長期稼働でDropboxトークンの自動更新が安定
- [ ] 2FA環境でもログイン～同期が可能

---

## M5 配布/運用

- [ ] CI（GitHub Actions）
  - [ ] lint / typecheck / test / coverage
  - [ ] キャッシュ活用
- [ ] リリース
  - [ ] バージョニング/タグ
  - [ ] CHANGELOG
  - [ ] pipx配布（任意）
- [ ] 運用
  - [ ] cron/launchd 手順検証
  - [ ] ログローテーション/監視（任意）

---

## テスト計画

- [ ] 単体テスト（パーサ/命名/差分計算）
- [ ] 結合テスト（Bookscan→Transfer→Dropboxをモックで）
- [ ] 疑似E2E（録画済みHTML/HTTPでの再現、VCR.py活用）
- [ ] 負荷/回復テスト（429/5xx注入、ネットワーク断）
- [ ] カバレッジ目標（例: 80%）

---

## セキュリティ/コンプライアンス

- [ ] 機微情報をログ出力しない（マスク）
- [ ] .env/.state/.cache/.logs をgitignore
- [ ] UAとレート制限の明示（規約順守）
- [ ] 依存脆弱性チェック（pip-audit 等）

---

## ドキュメント

- [x] README初版
- [x] TODO初版
- [x] .env.example 整備
- [ ] 使い方（各サブコマンド）詳細
- [ ] トラブルシュートの更新（CAPTCHA/TOTP/OAuth）
- [ ] 貢献ガイド（任意）

---

## バックログ（将来候補）

- [ ] 他ストレージ（GDrive/OneDrive/S3）
- [ ] Web UI / 進捗可視化
- [ ] Slack/メール通知
- [ ] Docker化、CIでのE2E
- [ ] Keychain/1Password CLI連携
