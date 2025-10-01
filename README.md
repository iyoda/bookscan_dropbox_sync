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
  - ログに資格情報や機微データを出力しない（CLIは SecretMaskFilter により DROPBOX_* や BOOKSCAN_* の値を自動マスク）
- ネットワーク
  - TLS必須、検証有効化、ユーザエージェント明示

## レート制限・リトライ・User-Agent

- User-Agent
  - Bookscan 側の HTTP は requests.Session.headers に Settings.USER_AGENT を適用
  - Dropbox SDK クライアント生成時の user_agent に Settings.USER_AGENT を渡す
  - 既定値: bookscan-dropbox-sync/0.1 (+https://github.com/iyoda/bookscan_dropbox_sync)（環境変数 USER_AGENT で上書き可能）

- レート制限（QPS）
  - Settings.RATE_LIMIT_QPS に基づく RateLimiter で最小間隔を強制
  - 既定 0.5（2秒/リクエスト）。0 以下で無効化
  - 適用箇所: Bookscan の GET/POST/ダウンロード、Dropbox の files_create_folder_v2 / files_upload / files_get_metadata

- リトライ
  - Bookscan HTTP: tenacity による指数バックオフ + jitter
    - 最大 5 回、wait_random_exponential(multiplier=1, max=10)
  - Dropbox SDK: SDKの自動リトライを使用
    - max_retries_on_error=5, max_retries_on_rate_limit=5
  - タイムアウト: HTTP_TIMEOUT（既定 60 秒）

例（.env）:
```env
RATE_LIMIT_QPS=0.5
USER_AGENT=bookscan-dropbox-sync/0.1 (+https://github.com/iyoda/bookscan_dropbox_sync)
HTTP_TIMEOUT=60
```

注意: 各サービスの規約を遵守し、必要に応じて RATE_LIMIT_QPS をさらに下げてください。


### RETRY_* 設定の説明

本ツールのリトライは TransferEngine により tenacity の指数バックオフ + jitter を用いて制御します。環境変数で以下を調整できます（.env で指定しない場合は既定値）。

- RETRY_MAX_ATTEMPTS (int, 既定 3)
  - 最大試行回数。1以上に丸められます。
- RETRY_BACKOFF_MULTIPLIER (float, 既定 0.1)
  - wait_random_exponential の multiplier。負値や0は安全側で 0.01 に補正されます。
- RETRY_BACKOFF_MAX (float, 既定 2.0)
  - バックオフの上限秒数。負値や0は安全側で 1.0 に補正されます。

実装メモ:
- 失敗のうち、FailureStore.classify_exception により retryable=True と分類されたもののみ再試行します（例: 429 Too Many Requests、5xx Server Error、ネットワーク一時障害など）。
- Dropbox SDK 側にも独自のリトライがあり、RateLimitError 等では SDK が Retry-After を尊重してスリープします（max_retries_on_error/max_retries_on_rate_limit の既定あり）。
- Bookscan HTTP アクセスには RateLimiter による最小間隔（QPS）も併用しています。

例:
```env
RETRY_MAX_ATTEMPTS=3
RETRY_BACKOFF_MULTIPLIER=0.1
RETRY_BACKOFF_MAX=2.0
```

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

### Dropbox OAuth権限取得（OAuth 2.0 with PKCE + Refresh Token）

developers.dropbox.com/oauth-guide に準拠した「Authorization Code + PKCE」での権限取得手順です。ネイティブCLI想定（クライアントシークレットを保持しない運用）で、長期の refresh_token を取得し、以後は短期 access_token を自動更新します（実装はM4予定／ここでは手動取得手順を記載）。

前提
- Dropbox App（Scoped Access）を作成済み
- App Consoleで必要スコープをON（例: files.content.write, files.content.read, files.metadata.write, files.metadata.read）
- Redirect URI に http://localhost:53682/callback を登録

1) 変数の用意
```bash
APP_KEY="your_app_key"                         # Dropbox App Key
REDIRECT_URI="http://localhost:53682/callback"
# スコープ（空白区切り）
SCOPES="files.metadata.read files.metadata.write files.content.read files.content.write"
# URLエンコード版（空白→%20）
SCOPE_ENC="files.metadata.read%20files.metadata.write%20files.content.read%20files.content.write"
```

2) PKCEのコードベリファイア/チャレンジ生成
```bash
# ランダムな code_verifier を生成（URL-safe Base64, paddingなし）
CODE_VERIFIER="$(python3 - <<'PY'
import os, base64
print(base64.urlsafe_b64encode(os.urandom(64)).rstrip(b'=').decode())
PY
)"
# S256 で code_challenge を作成
CODE_CHALLENGE="$(printf "%s" "$CODE_VERIFIER" | openssl dgst -binary -sha256 | openssl base64 -A | tr '+/' '-_' | tr -d '=')"
```

3) 認可URLを開く（token_access_type=offline が重要）
```bash
AUTH_URL="https://www.dropbox.com/oauth2/authorize?client_id=${APP_KEY}&response_type=code&token_access_type=offline&code_challenge=${CODE_CHALLENGE}&code_challenge_method=S256&redirect_uri=${REDIRECT_URI}&scope=${SCOPE_ENC}"
# macOS
open "$AUTH_URL"
# Linuxの場合は xdg-open "$AUTH_URL"
```
ブラウザで許可後、`REDIRECT_URI` に `?code=...` が付与されて遷移します。`code` を控えてください。

4) 認可コードをトークンに交換（client_secret不要・PKCE利用）
```bash
CODE="上で取得したコード"
curl -s https://api.dropboxapi.com/oauth2/token \
  -d grant_type=authorization_code \
  -d code="$CODE" \
  -d client_id="$APP_KEY" \
  -d code_verifier="$CODE_VERIFIER" \
  -d redirect_uri="$REDIRECT_URI"
```
レスポンス例（抜粋）:
```json
{
  "access_token": "...",      // 短期（数時間）
  "refresh_token": "...",     // 長期（これを保管）
  "expires_in": 14400,
  "token_type": "bearer",
  "scope": "..."
}
```

5) .env へ保存（本ツールの推奨変数）
```bash
# 必須
DROPBOX_APP_KEY=your_app_key
DROPBOX_REFRESH_TOKEN=your_refresh_token
DROPBOX_TOKEN_ROTATE=true

# 任意（機密クライアントとして運用する場合のみ）
# DROPBOX_APP_SECRET=your_app_secret
```

6) refresh_token から access_token を発行（参考：手動更新）
- シークレット無し（PKCE運用）
```bash
curl -s https://api.dropboxapi.com/oauth2/token \
  -d grant_type=refresh_token \
  -d refresh_token="$DROPBOX_REFRESH_TOKEN" \
  -d client_id="$DROPBOX_APP_KEY"
```
- シークレット有り（機密クライアント）
```bash
curl -s -u "$DROPBOX_APP_KEY:$DROPBOX_APP_SECRET" https://api.dropboxapi.com/oauth2/token \
  -d grant_type=refresh_token \
  -d refresh_token="$DROPBOX_REFRESH_TOKEN"
```

注意
- token_access_type=offline を付けないと refresh_token は発行されません
- App Console 側で有効化したスコープのみ使用可
- access_token は短期のため、運用では refresh_token から自動更新（M4で対応予定）
- 必要に応じた取り消し: `POST https://api.dropboxapi.com/2/auth/token/revoke`（Authorization: Bearer）

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

### State backend（SQLite/移行）

- 既定は JSON（.state/state.json）
- `STATE_BACKEND=sqlite` と `STATE_PATH=.state/state.db` を指定すると SQLite を使用
- 初回の SQLite 起動時、items テーブルが空で、同一パスの `.json`（例: `.state/state.json`）が存在する場合は自動でインポート（非破壊）
- 手動移行したい場合は JSON を編集後に再実行

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


## 開発者向けセットアップ（M0）

- 推奨: Python 3.11+ / macOS zsh

1) 仮想環境の作成/有効化
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

2) 依存のインストール（開発含む）
```bash
pip install -e ".[dev]"
```

3) pre-commit フックのセットアップ
```bash
pre-commit install
pre-commit run --all-files  # 初回整形
```

4) テスト実行
```bash
pytest
```

5) CLIの動作確認
```bash
bds --help
bds sync --dry-run
# もしくは（インストール前の一時実行）
PYTHONPATH=src python -m bds.cli sync --dry-run
```

注: srcレイアウトのため、未インストールの状態で `python -m bds.cli` を使う場合は `PYTHONPATH=src` を付与してください。開発時は `pip install -e .` を推奨します。

## デバッグ/ドライラン（BOOKSCAN_DEBUG_HTML_PATH）

HTTPログイン未実装のM1段階でも、デバッグ用HTMLから同期計画と転送フローを検証できます。

- 変数: `BOOKSCAN_DEBUG_HTML_PATH`
  - `samples/bookscan_list_sample.html` を同梱済み（2件の擬似アイテム）
  - ファイルパスを指定すると、そのHTML内の `.download-item` をパースします
  - ディレクトリを指定すると、*.html と *.htm を昇順で全て読み込み、結合パース（擬似ページネーション）
  - ワイルドカードパターン（例: `samples/*.html`）も指定可能
  - 文字列に生HTMLを渡すことも可能です（`<` を含む場合）
  - http(s) URL を指定することも可能です（そのURLのHTMLをパースします）

例（擬似ページネーションの利用）:
```bash
# ディレクトリ指定（samples/配下の *.html, *.htm を結合）
export BOOKSCAN_DEBUG_HTML_PATH=samples/
python -m bds.cli sync --dry-run

# グロブ指定
export BOOKSCAN_DEBUG_HTML_PATH="samples/*.html"
python -m bds.cli sync --dry-run
```

1) ドライラン（Dropboxへはアップロードしない）
```bash
# 仮想環境を有効化済み前提
export BOOKSCAN_DEBUG_HTML_PATH=samples/bookscan_list_sample.html
python -m bds.cli sync --dry-run
# 例:
# [DRY-RUN] planned actions: 2
# [DRY-RUN] upload book_id=1001 -> /Apps/bookscan-sync/Sample One.pdf ...
# [DRY-RUN] upload book_id=1002 -> /Apps/bookscan-sync/Second_ Work_.pdf ...
```

2) 実アップロード（Dropboxへ反映）
```bash
# 注意: ネットワークアクセスとDropbox書き込みを行います
export DROPBOX_ACCESS_TOKEN=xxxxx   # 固定アクセストークン（M1想定）
export BOOKSCAN_DEBUG_HTML_PATH=samples/bookscan_list_sample.html
python -m bds.cli sync
# 実行後、Dropboxの /Apps/bookscan-sync/ に2件がアップロードされます
```

3) 増分確認（再実行時に再アップロードされない）
```bash
python -m bds.cli sync --dry-run
# [DRY-RUN] planned actions: 0  となればOK（Stateにより差分なし）
```

補足:
- 出力先ルートは `DROPBOX_DEST_ROOT`（既定: `/Apps/bookscan-sync`）
- ダウンロード先の一時ディレクトリは `DOWNLOAD_DIR`（既定: `.cache/downloads`）
- 同期状態は `.state/state.json` に保存されます（gitignore対象）

## HTTPベース一覧取得（任意設定, M1最小）

- Bookscan の一覧HTMLを HTTP 経由で取得するための任意設定。ログイン不要/すでにセッションが有効なケースを想定。
- 環境変数:
  - BOOKSCAN_LIST_URL_TEMPLATE: 一覧ページのURL。`{page}` を含めるとページネーションし、含まれなければ1ページのみ取得
  - BOOKSCAN_LIST_MAX_PAGES: `{page}` 使用時の最大取得ページ数（既定: 1）
  - BOOKSCAN_LIST_STOP_ON_EMPTY: あるページで `.download-item` が0件になったら以降を打ち切る（既定: true）
- 開発時は `BOOKSCAN_DEBUG_HTML_PATH` が設定されていればそちらが優先されます。

### 簡易ログイン（任意）

- ログインフォームのPOST先とフィールド名を指定できます。成功/失敗に関わらず M1 では例外を投げません（ドライラン優先）。
- 環境変数:
  - BOOKSCAN_LOGIN_URL: ログインPOST先URL
  - BOOKSCAN_LOGIN_EMAIL_FIELD: メールアドレスのフィールド名（既定: email）
  - BOOKSCAN_LOGIN_PASSWORD_FIELD: パスワードのフィールド名（既定: password）
  - BOOKSCAN_LOGIN_TOTP_FIELD: TOTP のフィールド名（既定: otp、値の自動生成は将来対応）

## list サブコマンド（M2の一部を前倒し）

- 取得一覧（Bookscan）または保存済みStateを表示する簡易コマンド。
- 既定は `bookscan` の一覧を取得して表示します。`--source state` でState内容を表示します。

例（Bookscanの一覧を表示: デバッグHTMLを使用）
```bash
# 仮想環境を有効化済み前提
export BOOKSCAN_DEBUG_HTML_PATH=samples/bookscan_list_sample.html
python -m bds.cli list
# インストール済みなら:
# bds list
# 出力例:
# [LIST] bookscan items: 2
# [BOOKSCAN] id=1001 title='Sample One' ext=pdf size=12345 updated=2024-08-10T12:00:00Z
# [BOOKSCAN] id=1002 title='Second: Work?' ext=pdf size=2048 updated=2024-08-12
```

例（Stateの内容を表示）
```bash
# 既定の .state/state.json を表示
python -m bds.cli list --source state
# インストール済みなら:
# bds list --source state

# 任意のStateファイルを指定
python -m bds.cli list --source state  --state-pathの代わりに環境変数で:
STATE_PATH=.state/another.json python -m bds.cli list --source state
```

備考
- `list` の `bookscan` 表示は、`BOOKSCAN_DEBUG_HTML_PATH`（ファイル/ディレクトリ/ワイルドカード/生HTML/http(s)URL）を優先します。
- デバッグ入力が無い場合、任意設定の `BOOKSCAN_LIST_URL_TEMPLATE` があればHTTPで取得します（{page}対応）。
- いずれの場合も、`.download-item` 要素から簡易メタを抽出して表示します。

## 使い方（CLI）

- 初回ドライラン
  - 変更を加えずに予定されるアップロードを一覧表示
  - 例: `python -m bds.cli sync --dry-run`

- 本実行（増分）
  - 例: `python -m bds.cli sync`

- 範囲指定
  - 更新日でのフィルタ等（例: `--since 2024-01-01`）を提供予定

- ログ/詳細
  - `--json-log` でJSON構造化ログを有効化
  - `--log-file PATH` でログをファイル出力（パスまたはディレクトリ指定可。例: .logs/bds.log や .logs/）
  - 例:
    ```bash
    python -m bds.cli sync --dry-run --json-log --log-file .logs/
    python -m bds.cli list --json-log --log-file .logs/bookscan.log
    ```

- 認証補助
  - `python -m bds.cli login dropbox`
  - `python -m bds.cli login bookscan`
  - ブラウザを用いたOAuthフローを内蔵（将来）／現状は環境変数で代替


### 主なオプション

- --since YYYY-MM-DD: 更新日でフィルタ（指定日以降のみ対象）
- --exclude-ext EXT: 除外する拡張子（複数指定可）
- --min-size N, --max-size N: サイズで除外（バイト）
- --exclude-keyword WORD: タイトルに含むキーワードで除外（複数指定可）
- --json-log: ログをJSON形式にする
- --log-file PATH: ログをファイルに出力（ディレクトリ指定可）

### 終了コード

- 0: 成功
- 1: 実行時エラー（初期化/転送/I/O 等）
- 2: 設定エラー（例: 非ドライラン時に DROPBOX_ACCESS_TOKEN 等が不足）

## 同期ポリシー

- 同期方向
  - Bookscan → Dropbox（一方向）
- 命名規則
  - 基本: 「著者/タイトル（シリーズ）/版/巻/ファイル名.pdf」を安全なファイル名に正規化
  - 記号/絵文字は置換、長すぎる名前は短縮
- 重複/競合
  - Dropbox-Content-Hash で同一性を確認（同一ならスキップ、上書きしない）
  - 差異がある場合は "(v2)", "(v3)" のサフィックスでリネーム保存（WriteMode.add）
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
