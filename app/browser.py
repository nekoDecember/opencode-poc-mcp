"""新しく起動するChromiumを1ページだけ操作する。既存のWindowsブラウザには接続しない。"""

import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.async_api import async_playwright

from .images import Images, Mark


class Browser:
    def __init__(self, config: dict, images: Images):
        self.config = config["browser"]
        self.images = images
        self.state_path = Path(self.config["storage_state"])
        self.playwright = self.browser = self.context = self.page = None

    def proxy(self) -> dict | None:
        # Chromiumはproxy環境変数を自動では使わないため明示する。
        # 通常のHTTPプロキシ1台を想定。HTTP/HTTPSで別の値なら起動時に知らせる。
        http = os.environ.get("http_proxy", "")
        https = os.environ.get("https_proxy", "")
        if http and https and http != https:
            raise ValueError("ブラウザではhttp_proxyとhttps_proxyに同じHTTPプロキシURLを指定してください。")
        url = https or http
        if not url:
            return None
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("ブラウザのプロキシは通常のhttp:// URLを指定してください。")
        hostname = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        proxy = {"server": f"http://{hostname}:{parsed.port or 80}"}
        if parsed.username is not None:
            proxy["username"] = unquote(parsed.username)
        if parsed.password is not None:
            proxy["password"] = unquote(parsed.password)
        # Chromiumのbypassはカンマ区切り。localhost等もno_proxyで指定する。
        bypass = []
        for host in os.environ.get("no_proxy", "").split(","):
            host = host.strip()
            if host:
                bypass.append("*" + host if host.startswith(".") else host)
        if bypass:
            proxy["bypass"] = ",".join(bypass)
        return proxy

    async def get_page(self):
        if self.page is None or self.page.is_closed():
            if self.browser is None:
                self.playwright = await async_playwright().start()
                self.browser = await self.playwright.chromium.launch(headless=True, proxy=self.proxy())
            if self.context is None:
                self.context = await self.browser.new_context(
                    viewport={"width": self.config["viewport_width"], "height": self.config["viewport_height"]},
                    device_scale_factor=1, locale="ja-JP", timezone_id="Asia/Tokyo",
                    storage_state=str(self.state_path) if self.state_path.exists() else None,
                )
                self.context.set_default_timeout(self.config["timeout_ms"])
            self.page = await self.context.new_page()
        return self.page

    async def snapshot(self, max_chars: int) -> dict:
        page = await self.get_page()
        # Playwrightが解釈するCSSをそのまま返す。任意JSを実行するツールは公開しない。
        targets = await page.locator("a,button,input,textarea,select,[role=button],[contenteditable=true]").evaluate_all("""
        els => els.map((el, i) => {
          el.setAttribute('data-poc-target', String(i));
          return {selector: '[data-poc-target="' + i + '"]', tag: el.tagName.toLowerCase(),
            role: el.getAttribute('role'), type: el.getAttribute('type'),
            name: el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.textContent.trim().slice(0,120),
            visible: !!(el.getClientRects().length), disabled: !!el.disabled};
        }).filter(x => x.visible).slice(0,200)
        """)
        text = await page.locator("body").inner_text()
        return {"url": page.url, "title": await page.title(), "text": text[:max_chars],
                "text_truncated": len(text) > max_chars, "targets": targets,
                "targets_limit": 200, "selectors_valid_until": "次のsnapshotまたはページの更新まで。"}

    async def boxes(self, selector: str) -> dict:
        page = await self.get_page()
        bbox = await page.locator(selector).bounding_box()
        if bbox is None:
            raise ValueError("表示中の要素が見つかりません。")
        scroll = await page.evaluate("({x:scrollX,y:scrollY})")
        return {"viewport": bbox, "page": {**bbox, "x": bbox["x"] + scroll["x"], "y": bbox["y"] + scroll["y"]},
                "device_scale_factor": 1}

    async def screenshot(self, mode: str, selector: str | None, highlight_selectors: list[str]) -> list:
        page = await self.get_page()
        output = self.images.new_path("browser")
        # 要素画像は先にスクロールする。座標は撮影直前の状態から取得する。
        if mode == "element":
            if not selector:
                raise ValueError("elementにはselectorが必要です。")
            await page.locator(selector).scroll_into_view_if_needed()
        boxes = [(await self.boxes(s))["viewport"] for s in highlight_selectors]
        scroll = await page.evaluate("({x:scrollX,y:scrollY})")
        origin = {"x": 0, "y": 0}
        if mode == "element":
            origin = (await self.boxes(selector))["viewport"]
            await page.locator(selector).screenshot(path=str(output), animations="disabled")
        else:
            await page.screenshot(path=str(output), full_page=mode == "full_page", animations="disabled")
        metadata = self.images.metadata(output, "artifacts")
        marks = []
        for i, box in enumerate(boxes, 1):
            x = box["x"] - origin["x"] + (scroll["x"] if mode == "full_page" else 0)
            y = box["y"] - origin["y"] + (scroll["y"] if mode == "full_page" else 0)
            # 表示領域の外にはみ出した部分は画像範囲に切り詰める。
            right, bottom = min(metadata["width"], x + box["width"]), min(metadata["height"], y + box["height"])
            x, y = max(0, x), max(0, y)
            if right > x and bottom > y:
                marks.append(Mark(x=x, y=y, width=right - x, height=bottom - y, number=i))
        final = self.images.annotate(output, marks) if marks else output
        return self.images.content(final, "artifacts", original=metadata, mode=mode,
                                   marks=[m.model_dump() for m in marks], url=page.url)

    async def save_state(self) -> dict:
        await self.get_page()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(self.state_path), indexed_db=True)
        self.state_path.chmod(0o600)
        return {"saved": True, "note": "次回のブラウザ起動時に読み込みます。セッション期限には従います。"}

    async def close(self) -> None:
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.playwright = self.browser = self.context = self.page = None
