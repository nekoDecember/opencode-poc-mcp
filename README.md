# OpenCode向け個人利用PoC MCPサーバー

スクリーンショット参照、Giteaへの知識保存、日報のGit履歴、Chromium操作、画像への注釈、公開語だけを使う外部検索を提供する。Pythonの公式MCP SDKでStreamable HTTPを配信する。情報の解釈・整理・文章化はOpenCodeで行い、このサーバーから別のLLMは呼ばない。

現在の実装はTavily版。外部検索には利用者が発行したTavily APIキーを設定する。キーを設定しなくても、検索以外の機能は試せる。認証情報、実環境の設定、保存画像、ブラウザの認証状態はリポジトリへ含めない。

## 実行環境とバージョン

- 利用先はローカルWSL＋WSL内のDocker EngineとDocker Compose v2。Windows側のDocker Desktopを前提にしない。
- Python 3.12、`mcp==1.30.0`、`playwright==1.58.0`、`Pillow==12.1.0`、`httpx==0.28.1`。直接依存を固定している。MCP SDKは1.xの保守版を選び、`FastMCP.streamable_http_app()`をASGIへ組み込む。ブラウザはプロセスが終了するまで保持する。2.xへは自動更新しない。
- OpenCode接続例は2.2.2向けのV2形式。`mcp.servers`、`type=remote`、`url`、`oauth=false`を使う。SDK 1.xとの接続にはclassic initializeを使う`protocol=legacy`を明示する。画像を直接受け取るため`codemode=false`にしている。
- MCPのURLは`http://127.0.0.1:8000/mcp`。コンテナ内は`0.0.0.0:8000`、ホスト公開は仕様に合わせて`127.0.0.1`だけに限定する。LAN公開は行わない。
- サービスのDockerネットワークは既存の`bridge_common`だけを使い、Composeに`external: true`と`name: bridge_common`を指定している。共有認証は設けない。同じネットワーク上のコンテナからは到達できるので、信頼するコンテナだけを参加させる。

SDKの[1.30.0リリース](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v1.30.0)、[1.x公式資料](https://py.sdk.modelcontextprotocol.io/v1/)、OpenCodeの[2.2.2リリース](https://github.com/anomalyco/opencode/releases/tag/v2.2.2)、[MCP設定](https://opencode.ai/docs/mcp-servers/)、[設定スキーマ](https://opencode.ai/config.json)を2026-11-16に確認した。旧OpenCode V1の`mcp.<名前>`形式はこの接続例と異なる。利用中の版は`opencode --version`で確認する。

## 起動する

このフォルダをWSLのLinuxファイルシステム側へ置いて作業する。Snipping Toolの保存画像だけを`/mnt/c/...`経由で読み込む。

```sh
git clone https://github.com/nekoDecember/opencode-poc-mcp.git
cd opencode-poc-mcp
cp .env.example .env
cp config/config.example.toml config/config.toml
chmod 600 .env
```

`.env`の`SCREENSHOT_HOST_DIR`を、実際のWindowsユーザーの保存先にする。候補は`/mnt/c/Users/ユーザー名/Pictures/Screenshots`や`/mnt/c/Users/ユーザー名/OneDrive/Pictures/Screenshots`。日本語名や空白があれば引用符で囲む。Win＋Shift＋Sで撮影し、Snipping Toolの自動保存が有効なことと、実際にファイルが作られることを確認する。クリップボードだけにある画像は扱わない。

`config/config.toml`のGitea URL、ブランチ、日報ファイル名を変更する。リポジトリはREADME等で初期化しておく。`branch`を省略すると初回clone時の既定ブランチを使う。`.env`にGiteaのユーザー名・パスワードを設定する。Giteaの構成に応じてパスワード欄へアクセストークンを指定する場合も、HTTPS Basic認証として渡す。

検索にはTavilyの無料アカウントで発行した`TAVILY_API_KEY`を設定する。未設定でもサーバーは起動し、検索以外は利用できる。[方式と無料枠の比較](docs/search-services.md)を参照。

```sh
docker network inspect bridge_common
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 mcp
curl --noproxy '*' http://127.0.0.1:8000/health
```

`bridge_common`が存在しない場合は、そのWSLの既存ネットワーク構成を確認する。Composeは別のネットワークを自動作成しない。`/health`はプロセスの生存確認で、Gitea・検索キーの有効性は各ツールを呼んで確認する。

`restart: unless-stopped`でDocker Engine再起動後も起動する。WSL自体とDocker Engineが停止している間は利用できない。WSLでsystemdを利用する場合、Dockerサービスの有効化は既存の運用に合わせる。サーバーを短命なシェルセッションで常駐させる必要はない。

保存先はComposeの名前付きvolume`mcp_data`。作業コピー、生成画像、ブラウザ認証状態を保持する。`docker compose down`では残り、`down -v`は削除する。Windows画像は読み取り専用で、元画像を削除・変更しない。設定変更は`docker compose restart mcp`、`.env`変更は`docker compose up -d --force-recreate mcp`で反映する。

## プロキシ

`.env`または起動シェルで`http_proxy`・`https_proxy`・`no_proxy`と大文字版を設定できる。空でなければ小文字を優先し、両方を同じ値にそろえる。HTTPとHTTPSには、同じ通常のHTTPプロキシURLを設定する。

```dotenv
http_proxy=http://proxy.example.internal:8080
https_proxy=http://proxy.example.internal:8080
no_proxy=localhost,127.0.0.1,mcp,gitea.example.internal,.example.internal
```

| 通信 | 反映方法 |
| --- | --- |
| Python検索通信 | HTTPXの`trust_env=True`で環境変数を読む |
| GitのHTTPS通信 | Git/libcurlへ同じ環境変数を渡す。`GIT_ASKPASS`でBasic認証を渡す |
| 実行時Chromium | Playwrightの`launch(proxy=...)`へ明示的に変換する |
| apt・pip・Chromiumのビルド時取得 | Composeの標準proxy build argsで両表記を渡す |

Playwright用の`no_proxy`はカンマ区切りに変換し、`.example.internal`は`*.example.internal`にする。単純なホスト名・ドメイン・IPを使い、CIDR等の環境依存の解釈には頼らない。プロキシはコンテナから到達できるURLにする。`127.0.0.1`はコンテナ自身を指す。

proxy build argsはDockerfileで`ARG`や永続`ENV`へ再宣言せず、イメージへ残さない。ベースイメージのpullはDocker daemonの通信なので、必要ならWSL側のDocker daemonにも既存の方法でプロキシを設定する。ビルド環境の通信経路はDocker Engine側の管理に従う。Composeのサービスに追加ネットワークは作らない。

社内CAが必要なら既存のCA配布方法を使う。Pythonには`SSL_CERT_FILE`、Gitには`GIT_SSL_CAINFO`を設定できる。Chromiumの信頼ストアには別途CAを導入する。TLS検証を無効にする設定は設けていない。

## OpenCodeへ接続する

[opencode.example.jsonc](opencode.example.jsonc)の`mcp`を既存の`opencode.jsonc`へ追加する。既存のモデル設定や外部通信制限を上書きしない。ポートを変えた場合は接続URLも変える。

モデルを接続例から指定する場合だけ、WSLのOpenCode起動シェルに`OPENCODE_MODEL`を設定する。値は既存の接続先が持つ`provider ID/gpt6.1-sol`。provider IDは環境固有なので、架空の固定値を記載していない。`opencode models`で認識されている完全なIDを確認する。このサーバー側にモデルの設定や認証情報は不要。

```sh
opencode --version
opencode models
opencode mcp list
```

OpenCode内で`personal-poc`の接続を確認し、「最新のスクリーンショットを表示して」と依頼する。プロキシを利用するOpenCode側では`no_proxy`に`127.0.0.1,localhost`を含める。MCPサーバーの`.env`がOpenCode本体へ自動適用されるわけではない。

## ツールと使い方

引数の細部と既定値はMCPのツールスキーマ・日本語docstringでも参照できる。ファイルパスは各保存先からの相対パスを指定する。絶対パス、`..`、`.git`、シンボリックリンク経由の読み書きは受け付けない。

### スクリーンショット・画像

| ツール | 主な引数と用途 |
| --- | --- |
| `screenshot_list` | `limit=10`。新しい順にファイル名・相対パス・保存日時・画像サイズを返す |
| `screenshot_get` | `path`。指定画像を返す |
| `screenshot_latest` | 引数なし。最新画像を返す |
| `image_get` | `source`、`path`。Windows画像や生成画像を返す |
| `image_annotate` | `source`、`path`、`marks`。矩形・番号・ラベルを別画像に保存する |

`source`は`"screenshots"`または`"artifacts"`。画像取得ツールは説明テキストとMCPの`ImageContent(image/png)`を返す。`saved_at_jst`はファイルの更新時刻を日本時間へ変換したもの。撮影日時の専用メタデータではないため、コピーした画像の撮影日時とは異なる場合がある。常時監視はしない。

```json
{
  "source": "screenshots",
  "path": "Screenshot 2026-11-16 090000.png",
  "marks": [
    {"x": 100, "y": 160, "width": 240, "height": 80, "number": 1, "label": "保存", "color": "#e53935"}
  ]
}
```

座標は画像左上からのピクセル単位。枠が画像を超える場合はエラーにする。日本語ラベル用にNoto CJKを同梱する。元画像は残し、生成先は`artifacts`とする。画像を戻す際はRGBのPNGへ変換する。巨大な全体画像はOpenCodeの画像上限に達することがあるので、その場合は要素か表示範囲を撮る。

### Gitへの知識保存

| ツール | 主な引数と用途 |
| --- | --- |
| `repo_list` | 登録したリポジトリIDと用途を確認する |
| `repo_sync` | `repo`。初回clone、以後はfast-forwardだけで更新する |
| `repo_files` | `repo`、`directory="."`、`limit=300`。ファイルを一覧する |
| `repo_search` | `repo`、`text`、`limit=100`。固定文字列を検索する |
| `repo_read` | `repo`、`path`。UTF-8の本文を取得する |
| `repo_image` | `repo`、`path`。保存済みの画像をMCP画像コンテンツで取得する |
| `repo_write` | `repo`、`path`、`content`、任意の`sources`。本文を置き換え、参照元を記録する |
| `repo_copy_image` | `repo`、`source`、`path`、`destination`。画像をassets等へコピーする |
| `repo_delete` | `repo`、`path`。1ファイルだけを削除する |
| `repo_status` | `repo`。変更とstage済み差分の概要を確認する |
| `repo_diff` | `repo`、`paths`、`staged=false`。指定ファイルの差分を取得する |
| `repo_commit` | `repo`、`paths`、`message`、`push=true`。指定ファイルだけをcommitし、pushする |
| `repo_push` | `repo`。ローカルコミットを再送する |

`repo_sync`を呼んでから既存のREADMEや構造を読む。既存構造がなければMarkdown、索引のREADME、`assets/`を使う。構造を決めたり参照内容を要約したりする処理はMCPに入れない。社内Wikiの既存MCPから取得した情報をOpenCodeが整理し、`repo_write`へ渡す。

`sources`には参照元URLや資料の保存場所を文字列配列で渡せる。本文末尾へ「参照元」を追記するだけで、参照内容は取得しない。既存文書の上書き前には`repo_read`で確認する。

```json
{
  "repo": "knowledge",
  "path": "notes/playwright.md",
  "content": "# Playwrightの調査メモ\n\nOpenCodeが整理した本文。\n",
  "sources": ["https://playwright.dev/python/docs/intro", "社内資料の保存場所"]
}
```

`repo_commit.paths`は今回変更したファイルを明示する。既にstage済みの変更があれば停止する。他の未stage変更をまとめてコミットしない。`repo_diff`には未追跡ファイルの本文が出ないため、`repo_read`で確認する。設定ブランチへ直接pushしてよく、ブランチ省略時はcloneした既定ブランチへ保存する。force push、競合の自動解消、勝手なstashやresetは行わない。

pushだけが失敗してもローカルコミットは残る。`repo_status`で確認し、必要なら`repo_push`を呼ぶ。競合、stageの解除、ブランチ設定変更後の既存コピーの整理などは、`docker compose exec mcp sh`から人が確認する。認証値はGitのURLや設定へ書き込まず、`GIT_ASKPASS`経由で渡す。GitのstderrはMCPへ返さず、操作名と終了コードを返す。

### 日報・メモの履歴

| ツール | 主な引数と用途 |
| --- | --- |
| `daily_current` | `repo`。作業コピーの現在本文、HEAD、変更状態を返す |
| `daily_history` | `repo`、`start`、`end`、`limit=100`、`clock="committer"` |
| `daily_diff` | `repo`、`commit`。指定SHAで行われた日報の変更 |
| `daily_at` | `repo`、`commit`。指定SHA時点の日報本文 |

`daily_file`を持つリポジトリを選ぶ。参照前に`repo_sync`を呼ぶとリモートの最新を取得する。履歴は設定ファイルの変更コミットを対象とし、本文やメッセージの書式には依存しない。ファイルの改名追跡は行わない。期間は`YYYY-MM-DD`で、開始日の00:00から終了日翌日の00:00未満までをJSTで比較する。

```json
{"repo": "daily", "start": "2026-11-01", "end": "2026-11-16", "clock": "committer"}
```

`author_at_jst`はGitの作者日時、`committer_at_jst`はコミットを記録した日時。リベースや取り込みなどで異なることがある。実際の作業日を表す`work_date`は推定せず`null`で返す。OpenCodeがメッセージ・本文・差分を読んで判断する。日報には複数日の予定・会議・メモが混在していてよい。

`daily_diff`は通常は親との差分、マージは第1親との差分、最初のコミットは空ツリーとの差分を返す。`daily_at`は4〜40桁のコミットSHAを受け付ける。本文全文とメッセージはそのまま返す。小規模な1ファイル運用を想定し、履歴を列挙してから日時で絞る。

### ブラウザ操作とマニュアル作成

| ツール | 主な引数と用途 |
| --- | --- |
| `browser_navigate` | `url`。HTTP(S)へ移動する |
| `browser_snapshot` | `max_chars=15000`。本文と操作対象のselectorを取得する |
| `browser_click` | `selector`。一意の要素をクリックする |
| `browser_fill` | `selector`、`value`。入力欄を置き換える |
| `browser_fill_secret` | `selector`、`env_name`。許可済み環境変数の秘密値を入力する |
| `browser_select` | `selector`、`values`。selectのoption valueを選ぶ |
| `browser_key` | `key`、任意の`selector`。Enter、Tab等を送る |
| `browser_scroll` | `x=0`、`y=600`。ページをスクロールする |
| `browser_boxes` | `selector`。要素のviewport座標とページ座標を取得する |
| `browser_screenshot` | `mode="viewport"`、任意の`selector`・`highlight_selectors` |
| `browser_save_auth` | Cookie等の認証状態を保存する |
| `browser_close` | Chromiumを終了する |

新規のheadless Chromiumをコンテナ内で起動し、1つのコンテキストと操作ページを保持する。Windowsの既存Chromeやログイン状態は使わない。`browser_snapshot`のselectorは次のsnapshotや画面更新まで使える。CSSやPlaywrightのselectorも指定できる。複数要素に一致するとPlaywrightがエラーにする。iframe、ポップアップ、多タブの切り替えを専用に管理するツールは、このPoCには設けていない。

`mode`は`viewport`、`full_page`、`element`。`element`だけは`selector`が必要。`highlight_selectors`を指定すると撮影直前に位置を取得し、指定順の番号枠を付ける。表示範囲外の枠は切り詰め、画像と重ならなければ付けない。`device_scale_factor=1`なのでCSS座標と画像ピクセルは同じ縮尺になる。撮影後の画像には`image_annotate`で短いラベルも追加できる。

```json
{"mode": "viewport", "highlight_selectors": ["#save", "#next"]}
```

マニュアル作成は次の順で行う。

1. `repo_sync`で保存先を選び、既存の構造を読む。
2. `browser_navigate`、`browser_snapshot`、クリックや入力で操作する。
3. `browser_screenshot`や`image_annotate`で必要な画像を作る。
4. 返却された`artifacts`の相対パスを`repo_copy_image`へ渡し、`assets/step-01.png`等へ保存する。
5. OpenCodeがMarkdown本文を作り、`repo_write`で画像への相対リンクを記録する。
6. 索引READMEを更新し、本文・索引・画像だけを`repo_commit.paths`へ指定してpushする。

### ログインが必要なサイト

フォームは通常のブラウザツールで操作する。パスワード等は`.env`へ置き、`browser.secret_envs`へ環境変数名を登録して`browser_fill_secret`を呼ぶ。秘密値は引数や返却値へ出さない。ログイン後に`browser_save_auth`を呼ぶとCookie・localStorage・IndexedDBを保存し、次回の起動時に読み込む。更新されたセッションを残したい場合は改めて保存する。

保存ファイルは`/data/browser/auth.json`で、Gitや画像の保存先と分けている。ツールから認証ファイルの本文は取得できない。ログアウト時はサイトでログアウト後に状態を保存するか、ブラウザを閉じて保存ファイルを人が削除する。sessionStorageや端末証明書、Windows統合認証、対話的MFAをすべて引き継ぐ機能ではない。必要なら[Playwrightの認証状態](https://playwright.dev/python/docs/auth)に対応したstorage stateを人が用意する。ログイン後の画面本文や画像自体には秘密情報が表示される場合があるので、保存する画面を選ぶ。

### 制限付き外部検索

`search_terms`で公開語の登録内容を確認し、`external_search(term_ids, limit=5)`を呼ぶ。人が登録した語だけを組み合わせる。未登録値は送信しない。社内名・質問文・ログをqueryとして渡す引数はない。検索先はTavilyの一般Web検索で、GitHubやWikipedia内だけの検索ではない。

Tavily Researcherはカードなしで1,000 credits/月、100 requests/分。basic検索は1 credit/回。PAYGOを有効にせず使う。無料枠を使い切ると提供元で停止し、サーバーはエラーをそのまま示す。自動再試行や別サービスへの切り替えはしない。[選定資料と公式出典](docs/search-services.md)を参照。

## 基本動作を確認する

自動テスト一式は設けず、1本の確認スクリプトを用意した。

```sh
docker build -t opencode-poc-mcp:check .
docker run --rm --network none --shm-size=1g opencode-poc-mcp:check python -m scripts.smoke
```

確認用コンテナ内で一時的なHTTPS Git接続先・操作ページ・検索APIを起動し、実際のStreamable HTTP接続から全ツールを呼ぶ。`--network none`でもコンテナ内のloopbackで動く。通常サービスのネットワークを変更する操作ではない。既存のGitea・保存画像・認証情報は使わない。

確認内容はMCP initializeとtools/list、全ツールの呼び出し、PNGの復号、HTTPS Basicでのclone・commit・push、指定外のファイルがコミットされないこと、JSTの期間と作者/記録日時の違い、画像の別保存、Chromiumの操作と認証状態の再利用、公開語からのAPI送信、未登録語・範囲外パス・参照専用repoの拒否。Tavily実APIでの検索結果取得やWSL固有のマウントは別確認とする。

実施結果と未確認の範囲は[検証記録](docs/verification.md)を参照。利用先では、Snipping Toolの実画像、実Gitea、実Tavilyキー、OpenCodeの画像表示をそれぞれ一度確認する。
