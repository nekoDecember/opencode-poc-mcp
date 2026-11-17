"""公開語IDだけを受け取り、Tavilyの公式Web検索APIへ送る。"""

import os

import httpx


class Search:
    def __init__(self, config: dict):
        self.config = config["search"]

    def terms(self) -> dict:
        return {"provider": "tavily", "scope": "general_web", "enabled": self.config["enabled"],
                "terms": self.config["terms"], "max_terms": self.config["max_terms"]}

    def query(self, term_ids: list[str]) -> str:
        if not 1 <= len(term_ids) <= self.config["max_terms"]:
            raise ValueError("公開語IDを上限以内で指定してください。")
        if any(key not in self.config["terms"] for key in term_ids):
            # 未登録値は外部へ送らず、ログにも反映しない。
            raise ValueError("未登録の公開語IDがあります。search_termsを確認してください。")
        return " ".join(self.config["terms"][key] for key in dict.fromkeys(term_ids))

    async def search(self, term_ids: list[str], limit: int) -> dict:
        query = self.query(term_ids)
        if not self.config["enabled"]:
            raise ValueError("検索は設定で無効になっています。")
        key = os.environ.get(self.config["api_key_env"], "")
        if not key:
            raise ValueError("検索APIキーが未設定です。無料アカウントのキーを環境変数へ設定してください。")
        if not 1 <= limit <= self.config["max_results"]:
            raise ValueError("検索件数が設定の上限を超えています。")
        # 要約生成やResearchは使わず、basic検索結果の抜粋とURLだけを返す。
        payload = {"query": query, "topic": "general", "search_depth": "basic", "max_results": limit,
                   "auto_parameters": False, "include_answer": False, "include_raw_content": False,
                   "include_images": False}
        try:
            async with httpx.AsyncClient(trust_env=True, timeout=30) as client:
                response = await client.post(self.config["endpoint"], json=payload,
                                             headers={"Authorization": f"Bearer {key}"})
        except httpx.RequestError:
            raise ValueError("検索APIに接続できません。ネットワークとプロキシを確認してください。") from None
        if not response.is_success:
            raise ValueError(f"検索APIのHTTPエラー: {response.status_code}。認証・無料枠・呼び出し上限を確認してください。")
        data = response.json()
        return {"provider": "tavily", "scope": "general_web", "query": query,
                "results": [{key: result.get(key) for key in ("title", "url", "content", "score")}
                            for result in data.get("results", [])]}
