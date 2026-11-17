# 外部検索APIの選定

確認日: 2026-11-16。一般Web検索の第一候補としてTavilyを採用した。アカウントの作成とAPIキーの発行は利用者が行う。既存契約がない状態でも無料枠から始められ、検索結果ページを独自にスクレイピングする必要がない。

## 比較

| 候補 | 対象 | 認証・登録 | 無料枠と上限 | 判断 |
| --- | --- | --- | --- | --- |
| Tavily Search | 一般Web。技術情報や企業情報も対象 | 無料アカウントとBearer APIキー。カード不要 | Researcherは1,000 credits/月、100 requests/分。basic検索は1 credit/回。PAYGOを有効にしなければ枠超過時に停止 | 採用。basic固定で月1,000回相当。他用途にも同じcreditsを使えば回数は減る |
| Exa Search | 一般Web。企業情報等の専用索引もある | アカウントとAPIキー。Freeは支払い方法不要 | 毎月$10、初回オンボーディングで追加$10。FreeのSearchは10 QPS。利用する検索種別・追加内容で消費額が変わる | 代替候補。今回のコードには組み込まず、APIごとの料金計算を避ける |
| Brave Search API | 一般Web | アカウント、プラン有効化、APIキー、カードが必要 | 独立した無料プランはなく、各プランに毎月$5の無料credit。Searchでは約1,000件相当。カードの$0/$1確認がある | カード不要を優先して見送り。結果の保持にもプラン条件がある |
| Google Custom Search JSON API | Programmable Search Engine | APIキーと検索エンジンID | 既存利用者には100回/日の無料枠があるが、新規受付終了。既存利用者も2027-01-01までに移行が必要 | 新規PoCでは採用しない |
| DuckDuckGo Instant Answer API | 一部の即時回答 | 従来の公開API | 一般Webの検索結果APIではない | 一般Web検索の代用にしない |
| GitHub API・Wikipedia/MediaWiki API | GitHub内、百科事典内の限定検索 | APIごとの条件 | 検索範囲が限定される | OSS・用語確認の補助候補。一般Web検索と同等には扱わない |

Tavilyの自動利用は公開されている[Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)を使い、[Platform Terms](https://www.tavily.com/terms)の範囲で行う。検索結果の本文や画像に関する権利までAPI利用料で取得するものではない。知識へ保存するときは参照URLを残す。

Tavilyでは`include_answer=false`、`auto_parameters=false`、`search_depth=basic`を固定する。別のLLMやResearch APIを呼ばず、検索結果のtitle・URL・抜粋・scoreをそのまま返す。独自の再試行や有料サービスへのフォールバックはしない。検索範囲や順位は提供元に依存し、Google等と同じ結果になることは保証しない。

## 送信できる語

`config.toml`の`[search.terms]`を人が編集する。MCPの引数は`term_ids`だけで、queryや任意の追加語は受け付けない。

```toml
[search.terms]
playwright = "Playwright"
timeout_error = "TimeoutError"
```

```json
{"term_ids": ["playwright", "timeout_error"], "limit": 5}
```

送信queryは`Playwright TimeoutError`となる。未登録IDが1件でもあれば、HTTP通信前に拒否する。設定は起動時に読むだけで、MCPには公開語や接続先を書き換えるツールを設けていない。Composeでも設定ファイルを読み取り専用でマウントする。

この制限は外部検索ツールの入力に適用される。ブラウザは仕様どおり任意のHTTP(S)サイトへ移動・入力できるため、OpenCode側でも社内質問やログを外部の検索フォームへ入力しない運用にする。既存のOpenCode外部通信制限は変更しない。

検索APIを使う契約自体も認められない場合は`search.enabled=false`にする。その場合、登録語を使った手動検索、公式ドキュメントの既知URL参照、GitHub等の限定検索を代替とする。無契約・無登録・無制限の一般Web検索を、このPoCが提供するとは扱わない。

## 公式資料

- Tavily: [料金](https://www.tavily.com/pricing)、[credit](https://docs.tavily.com/documentation/api-credits)、[呼び出し上限](https://docs.tavily.com/documentation/rate-limits)、[無料枠終了時の扱い](https://help.tavily.com/articles/8298987937-billing-credits-usage-limits)。
- Exa: [料金](https://exa.ai/pricing)、[無料creditと上限](https://exa.ai/docs/admin/billing)。
- Brave: [無料credit・登録・結果保持のFAQ](https://api-dashboard.search.brave.com/documentation/resources/help-feedback)。
- Google: [Custom Search JSON APIの受付・終了予定](https://developers.google.com/custom-search/v1/overview)。
- DuckDuckGo: [公式公開ソースのAPI説明](https://github.com/duckduckgo/duckduckgo-publisher/blob/master/share/site/duckduckgo/api.tx)。

料金と上限は変更されるため、キー発行時に管理画面の表示も確認する。
