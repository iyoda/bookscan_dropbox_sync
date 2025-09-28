# bookscan_dropbox_sync

Bookscan（ブックスキャンの電子書籍ダウンロードページ）から入手可能なPDFを、Dropboxの指定フォルダへ同期するためのユーティリティの計画と設計ドキュメント。

本リポジトリでは、まず計画と設計を明文化し、その後段階的に実装していきます。

- 目的
  - Bookscanで提供されるPDFをローカルにダウンロードし、Dropboxに自動アップロードする
  - 増分同期（新規/更新のみ）を行い、重複アップロードを避ける
  - 定期実行（cron/launchd等）に耐える堅牢なCLIツールを提供する

- 想定ユースケース
  - 定期的にBookscanへ新規PDFが追加されるユーザが、Dropboxへ自動で集約したい
  - ローカルや別PCとの共有、バックアップ、検索（Dropbox上の検索機能）を活用したい

- 非ゴール
  - Bookscanのサイト仕様・利用規約に反するアクセスや高負荷なクローリング
  - GUIアプリ（初期段階ではCLIに限定）


## 全体アーキテクチャ

- データフロー（概略）
  1. 認証
     - Bookscan: メール/パスワード/（必要に応じてTOTP）のログイン
     - Dropbox: アプリトークン（推奨はリフレッシュトークン＋短期アクセストークン自動更新）
  2. 取得
     - Bookscanの「ダウンロード可能一覧」を一覧化（ページネーション対応）
     - 各アイテムのメタデータ（タイトル、拡張子、サイズ、更新日 等）を取得
  3. 計画
     - これまで同期済みの状態（State）と比較し、必要なダウンロード/アップロードの差分を決定
  4. 転送
     - PDFを一時ディレクトリにダウンロード
     - ハッシュ/サイズ/ページ数等の簡易検証（可能な範囲で）を行う
     - Dropboxの所定パスへアップロード（フォルダ作成、重複回避、リネームポリシー適用）
  5. 記録
     - 同期結果（成功/失敗、リトライ履歴、ファイルIDとDropboxパスのマッピング）をStateに永続化

- コンポーネント
  - BookscanClient: 認証、一覧取得、ファイル取得
  - DropboxClient: 認証（トークン更新含む）、フォルダ/ファイル操作、アップロード
  - StateStore: 同期済み情報の保存（SQLiteまたはJSON）
  - SyncPlanner: 差分計算、衝突解決、命名規則適用
  - TransferEngine: ダウンロード/アップロード、検証、再試行/バックオフ
  - CLI/Runner: 設定読込、コマンド実行、ログ、終了コード管理


## 設計方針・技術選定

- 言語/ランタイム
  - Python 3.11+（CLI作成、HTTP、状態管理、クロスプラットフォームのバランス）
- HTTP/自動化
  - まずはrequests＋BeautifulSoup等でのHTTPアクセス（クッキー管理、フォームログイン）
  - 2FAや動的コンテンツ、Bot検知が強い場合はPlaywright（ヘッドレス）でのフォールバックを用意
- クラウドSDK
  - Dropbox Python SDK（短期アクセストークンの自動更新に対応）
- 状態管理
  - 小規模用途: JSON（.state/state.json）
  - 中規模/将来拡張: SQLite（.state/state.db）
- CLI
  - TyperまたはClick（`sync`, `list`, `login`, `dry-run` 等のサブコマンド）
- ログ
  - 標準出力（INFO/ERROR）、ファイル出力（.logs配下）、構造化（JSON）オプション
- 冪等性/信頼性
  - リトライ（指数バックオフ、Jitter）
  - 増分判定（Etag/サイズ/更新日時/ハッシュ）
  - 中断/再開に強い設計（部分ダウンロードの再開は段階2以降）


## セキュリティとコンプライアンス

- 資格情報
  - .envに置くがVCSへはコミットしない（.gitignore）
  - macOS Keychainや1Password CLIへの移行も将来対応
- 利用規約/負荷
  - Bookscanの利用規約に従うこと
  - レート制限/待機時間を十分に確保（ユーザ設定可）
- 個人情報
  - ログに資格情報や機微データを出力しない
- ネットワーク
  - TLS必須、検証有効化、ユーザエージェント明示


## セットアップ

- 前提
  - macOS（動作確認環境）
  - Python 3.11+、pip（またはuv/pipx）
  - Dropboxアカウント、Bookscanアカウント

- 依存インストール（実装後に提供）
  - `requirements.txt` もしくは `pyproject.toml` を提供予定
  - 例:
    - `pip install -r requirements.txt`
    - あるいは `uv pip install -r requirements.txt`

- Dropboxアプリ設定（推奨フロー）
  1. https://www.dropbox.com/developers/apps で新規アプリ作成（Scoped Access）
  2. 権限（scopes）に `files.content.write`, `files.content.read`, `files.metadata.write`, `files.metadata.read` 等を付与
  3. リダイレクトURI（ローカルCLI用に `http://localhost:53682/callback` 等）を登録（後日CLIで使用）
  4. App key/secret を保存
  5. CLIからのOAuthでRefresh Tokenを取得（初期版は簡易運用として「長期アクセストークン」を使うオプションも記載）

- 環境変数（.env推奨）
  ```
  # Bookscan
  BOOKSCAN_EMAIL=your_email@example.com
  BOOKSCAN_PASSWORD=your_password
  BOOKSCAN_TOTP_SECRET= # 任意（TOTPが必要な場合）
  BOOKSCAN_BASE_URL=https://www.bookscan.co.jp # 変更不要の想定

  # Dropbox（簡易運用：固定アクセストークンを使用する場合）
  DROPBOX_ACCESS_TOKEN=

  # Dropbox（推奨：OAuth/Refresh Token運用）
  DROPBOX_APP_KEY=
  DROPBOX_APP_SECRET=
  DROPBOX_REFRESH_TOKEN=
  DROPBOX_TOKEN_ROTATE=true

  # 同期先
  DROPBOX_DEST_ROOT=/Apps/bookscan-sync

  # 動作パラメータ
  DOWNLOAD_DIR=.cache/downloads
  STATE_BACKEND=sqlite # または json
  STATE_PATH=.state/state.db # jsonの場合は .state/state.json
  SYNC_MODE=incremental # incremental|full|dry-run
  CONCURRENCY=2
  RATE_LIMIT_QPS=0.5
  USER_AGENT=bookscan-dropbox-sync/0.1 (+https://github.com/iyoda/bookscan_dropbox_sync)
  HEADLESS=true
  HTTP_TIMEOUT=60
  ```

- 参考ディレクトリ構成（実装時に追加）
  ```
  .
  ├─ src/
  │  ├─ bds/
  │  │  ├─ __init__.py
  │  │  ├─ cli.py            # CLIエントリ
  │  │  ├─ config.py
  │  │  ├─ bookscan_client.py
  │  │  ├─ dropbox_client.py
  │  │  ├─ state_store.py
  │  │  ├─ sync_planner.py
  │  │  ├─ transfer.py
  │  │  └─ util/
  │  └─ ...
  ├─ tests/
  ├─ .env.example
  ├─ .state/                 # 状態ファイル（gitignore）
  ├─ .cache/                 # 一時DL（gitignore）
  ├─ .logs/                  # ログ（gitignore）
  ├─ requirements.txt / pyproject.toml
  └─ README.md
  ```


## 使い方（実装予定のCLI）

- 初回ドライラン
  - 変更を加えずに予定されるアップロードを一覧表示
  - 例: `python -m bds.cli sync --dry-run`

- 本実行（増分）
  - 例: `python -m bds.cli sync`

- 範囲指定
  - 更新日でのフィルタ等（例: `--since 2024-01-01`）を提供予定

- ログ/詳細
  - `--verbose` / `--json` ログ出力切替

- 認証補助
  - `python -m bds.cli login dropbox`
  - `python -m bds.cli login bookscan`
  - ブラウザを用いたOAuthフローを内蔵（将来）／現状は環境変数で代替


## 同期ポリシー

- 同期方向
  - Bookscan → Dropbox（一方向）
- 命名規則
  - 基本: 「著者/タイトル（シリーズ）/版/巻/ファイル名.pdf」を安全なファイル名に正規化
  - 記号/絵文字は置換、長すぎる名前は短縮
- 重複/競合
  - Dropbox上に同名がある場合はハッシュ/サイズ/更新日時で同一性を確認
  - 差異がある場合は「(dup)」「(v2)」などのサフィックス付与、または上書きポリシー選択式
- 増分判定
  - Bookscan側ID＋更新日時＋サイズ/ハッシュをStateに記録
- 除外/フィルタ
  - 例: サンプル、0バイト、拡張子がPDF以外 等を除外
- 失敗時
  - リトライ（指数バックオフ）
  - 永続的失敗はスキップ記録し、次回に再評価


## 運用

- スケジューリング例（cron）
  ```
  # 毎日午前3時に実行（仮想環境のactivateは適宜）
  0 3 * * * cd /Users/iyoda/Projects/atikoro/bookscan_dropbox_sync && \
    /usr/bin/env -S bash -lc 'source .venv/bin/activate && python -m bds.cli sync >> .logs/cron.log 2>&1'
  ```

- launchd（macOS）や他のジョブスケジューラも可
- ログローテーションはsize/timeで分割を検討
- アップデート時は`dry-run`で影響確認してから本実行


## トラブルシュート

- Bookscanで2FA/TOTPが有効
  - `BOOKSCAN_TOTP_SECRET` の設定、または初回のみ手動入力UI（将来）
- CAPTCHAに阻害される
  - レートをさらに下げる、Playwrightフォールバックを使用、間隔を空ける
- HTTP 429/5xx
  - 指数バックオフと最大試行回数を調整
- Dropboxで「パスが長すぎる/権限不足」
  - 命名規則の短縮、スコープ見直し、フォルダパスの再設定
- PDFの破損
  - 再ダウンロード、サイズ/ハッシュ検証、部分DLの再試行（段階2以降）


## 将来拡張

- 他ストレージ（Google Drive/OneDrive/S3）対応
- Web UI（進捗表示、設定編集）
- 完全なOAuth内蔵フロー（ブラウザ起動、リフレッシュ自動管理）
- 差分の通知（Slack/メール）
- 並行ダウンロードの最適化、帯域制御
- Docker化、CI/CD、パッケージ配布（pipx）


## ライセンス/免責

- 個人ユース想定。各サービスの利用規約に従ってください。
- 本ツールの利用により生じた損害について、作者は責任を負いません。


## 進捗と次のステップ

- このREADMEは計画と設計の初版です。次はTODO.mdの詳細タスクに従って実装を開始します。
