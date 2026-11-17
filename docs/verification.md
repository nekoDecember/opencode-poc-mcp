# 基本動作の検証記録

実施日: 2026-11-16。

## 確認環境

実装作業環境はmacOS上のDocker Engine 29.5.2（Colima、Linux arm64）。Compose設定の展開にはDocker Compose 5.5.1の`docker-compose`コマンドを使った。利用先のWSLでは実行していない。

Python 3.12のDockerイメージを実際にビルドし、固定したMCP SDK 1.30.0、Playwright 1.58.0、Pillow 12.1.0、HTTPX 0.28.1をインストールした。Chromiumの依存取得と起動を確認した。

## 実行結果

`scripts/smoke.py`からStreamable HTTPへ接続し、initialize、tools/list、公開している36個すべてのツールを呼び出した。全ツールを実際のMCP接続を通して確認した。

```json
{
  "tools_called": 36,
  "transport": "streamable-http",
  "image_content": "PNG verified",
  "git": "HTTPS Basic clone/commit/push verified",
  "search": "local API fixture only"
}
```

| 対象 | 確認した内容 |
| --- | --- |
| MCP・画像 | 接続、一覧、画像コンテンツのPNG復号、保存日時とファイル名、最新画像・指定画像の取得 |
| Git | 一時的なHTTPS＋Basic認証のGit接続先でclone・更新・ファイル操作・commit・push。別の未コミットファイルがコミットに混ざらないこと |
| 資格情報 | fixtureの認証値がリモートURLやサーバーログへ入らないこと。実行時は`GIT_ASKPASS`で渡す |
| 日報 | 現在本文、JSTの日付境界、作者日時と記録日時を別日とした履歴絞り込み、初回コミットの差分、指定SHAの本文 |
| ブラウザ | 新規Chromium、URL移動、本文・操作対象、クリック、入力、秘密値入力、選択、キー、スクロール、要素座標、3種類の撮影 |
| 画像加工 | 元画像が変わらないこと、番号枠・日本語ラベル、assetsへの保存と画像としての再取得。生成画像を目視確認 |
| 認証状態 | localStorageを保存し、Chromiumを閉じて起動し直した後も読み込めること |
| 検索 | ローカルのAPI代役へ公開語だけから作ったqueryを送信し、抜粋とURLを返すこと。未登録語ではAPI呼び出しが増えないこと |
| 保存範囲 | `..`、`.git`、シンボリックリンク、参照専用リポジトリへの書き込みを拒否すること |
| Compose | `external/name=bridge_common`のみ、ホスト公開は127.0.0.1、設定とWindows画像の読み取り専用マウント、restart設定 |
| プロキシ | Composeの`.env`解決とbuild/runtime両方への大文字・小文字の反映、Python側の正規化、Chromiumのproxy/bypass変換 |
| 設定 | Python構文、TOML、JSONCの読み込み。OpenCode V2の公式MCP資料・設定スキーマとの照合 |

確認用コンテナは`--network none`で起動し、HTTPS Gitとページ・検索APIはコンテナ内のloopbackに一時起動した。検証用の認証値はfixture専用で、ユーザーの認証情報は使っていない。既存サービスのデータやネットワークは変更していない。

## 利用先で必要な確認

以下は現地のパス・URL・資格情報がないため未確認。コードと設定項目は用意している。

- WSLから見たSnipping Toolの保存先とWindowsファイルの読み取り権限。
- 利用先の既存`bridge_common`でのCompose起動と再起動。検証用Macには同名ネットワークがないため作成していない。
- 実Giteaへの接続、実際のブランチ・日報ファイル、組織固有の認証設定。
- Tavily実APIの認証と検索結果。無料キーは未発行。利用条件・無料枠・認証方式は[公式資料から確認](search-services.md)した。
- 社内プロキシを通した実通信と、社内CAの信頼設定。
- OpenCode 2.2.2の実クライアント接続と`gpt6.1-sol`への画像入力。MCP SDKクライアントでの接続と画像返却は確認済み。

常駐サービスはこのMacへ配備していない。利用先でREADMEの手順を実行し、`opencode mcp list`と最新スクリーンショットの表示を確認する。
