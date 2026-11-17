"""MCPの窓口。python -m app.serverでStreamable HTTPを起動する。"""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
import shutil
from typing import Literal
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from playwright.async_api import Error as PlaywrightError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount
import uvicorn

from .browser import Browser
from .common import inside, load_config, normalize_proxy_env
from .images import FORMATS, Images, Mark
from .repositories import Repositories
from .search import Search

normalize_proxy_env()
config = load_config()
images = Images(config)
repos = Repositories(config)
browser = Browser(config, images)
search = Search(config)
browser_lock = asyncio.Lock()


# Docker内は全インターフェース、ホスト側はComposeで127.0.0.1に限定する。
# セッション状態はブラウザ1個だけで保持する。複数workerにはしない。
mcp = FastMCP("opencode-poc", host=config["server"]["host"], port=config["server"]["port"],
              stateless_http=True, json_response=True,
              instructions="画像・Git・日報・ブラウザ・公開語検索を提供します。解釈と文章化はクライアントで行ってください。")


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request):
    return JSONResponse({"status": "ok"})


def bounded(value: int, maximum: int) -> int:
    if not 1 <= value <= maximum:
        raise ValueError(f"1〜{maximum}で指定してください。")
    return value


@mcp.tool()
async def screenshot_list(limit: int = 10) -> dict:
    """Snipping Toolの保存画像を新しい順で返す。limitは1〜100。時刻は保存ファイルのmtime(JST)。"""
    return {"images": images.recent(bounded(limit, 100))}


@mcp.tool()
async def screenshot_get(path: str) -> list:
    """保存先からの相対pathを指定し、画像本体・ファイル名・保存日時を返す。"""
    return images.content(images.path("screenshots", path), "screenshots")


@mcp.tool()
async def screenshot_latest() -> list:
    """最新のSnipping Tool画像をMCP画像コンテンツで返す。"""
    recent = images.recent(1)
    if not recent:
        raise ValueError("保存画像がありません。Snipping Toolの自動保存先を確認してください。")
    return images.content(images.path("screenshots", recent[0]["path"]), "screenshots")


@mcp.tool()
async def image_get(source: Literal["screenshots", "artifacts"], path: str) -> list:
    """Windows画像またはブラウザ・加工画像を、画像本体とメタデータで返す。"""
    return images.content(images.path(source, path), source)


@mcp.tool()
async def image_annotate(source: Literal["screenshots", "artifacts"], path: str, marks: list[Mark]) -> list:
    """左上を原点とする画像ピクセル座標の矩形・番号・短いラベルを重ね、別保存して画像を返す。"""
    original = images.path(source, path)
    output = images.annotate(original, marks)
    return images.content(output, "artifacts", original=images.metadata(original, source))


@mcp.tool()
async def repo_list() -> dict:
    """選べるリポジトリID、ブランチ、書き込み可否、日報ファイルを返す。認証値は返さない。"""
    return {name: {key: spec.get(key) for key in ("branch", "writable", "daily_file")}
            for name, spec in config.get("repositories", {}).items()}


@mcp.tool()
async def repo_sync(repo: str) -> dict:
    """登録済みrepoをcloneまたはfast-forwardする。既存の未コミット変更や競合があれば停止する。"""
    return repos.sync(repo)


@mcp.tool()
async def repo_files(repo: str, directory: str = ".", limit: int = 300) -> dict:
    """repo内の相対directoryにあるファイルを一覧する。.gitは扱わない。limitは1〜10000。"""
    return repos.files(repo, directory, bounded(limit, 10000))


@mcp.tool()
async def repo_search(repo: str, text: str, limit: int = 100) -> dict:
    """テキストファイルを固定文字列で検索し、パス・行番号・原文を返す。外部送信しない。"""
    if not text:
        raise ValueError("検索する文字列を指定してください。")
    return repos.search(repo, text, bounded(limit, 1000))


@mcp.tool()
async def repo_read(repo: str, path: str) -> dict:
    """repo内の相対pathにあるUTF-8ファイルをそのまま返す。"""
    return {"repo": repo, "path": path, "text": repos.read(repo, path)}


@mcp.tool()
async def repo_image(repo: str, path: str) -> list:
    """repo内の既存assets等のPNG・JPEG・WebPを、画像コンテンツとして取得する。"""
    root = repos.path(repo)
    target = inside(root, path)
    if target.suffix.lower() not in FORMATS:
        raise ValueError("PNG、JPEG、WebPを指定してください。")
    return images.content(target, "repository", root=root, repo=repo)


@mcp.tool()
async def repo_write(repo: str, path: str, content: str, sources: list[str] | None = None) -> dict:
    """UTF-8本文を書き込む。sourcesは参照URL・資料の場所で、末尾にMarkdownの参照元として追記する。"""
    if sources:
        content = content.rstrip() + "\n\n## 参照元\n\n" + "".join(f"- {source}\n" for source in sources)
    return repos.write(repo, path, content)


@mcp.tool()
async def repo_copy_image(repo: str, source: Literal["screenshots", "artifacts"], path: str, destination: str) -> dict:
    """画像を選択repoの相対destinationへコピーする。通常はassets/ファイル名を指定する。"""
    repos.writable(repo)
    original = images.path(source, path)
    target = inside(repos.path(repo), destination)
    if target.suffix.lower() != original.suffix.lower():
        raise ValueError("画像と同じ拡張子を指定してください。")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(original, target)
    return {"repo": repo, "path": destination, "bytes": target.stat().st_size}


@mcp.tool()
async def repo_delete(repo: str, path: str) -> dict:
    """repo内の指定ファイルだけを削除する。ディレクトリの一括削除はしない。コミットは別操作。"""
    repos.writable(repo)
    inside(repos.path(repo), path).unlink()
    return {"deleted": path}


@mcp.tool()
async def repo_status(repo: str) -> dict:
    """ブランチ、作業中の変更、stage済み変更の概要を返す。"""
    return repos.status(repo)


@mcp.tool()
async def repo_diff(repo: str, paths: list[str], staged: bool = False) -> dict:
    """指定ファイルのGit差分を返す。新規の未追跡ファイル本文はrepo_readで確認する。"""
    if not paths:
        raise ValueError("ファイルを指定してください。")
    for path in paths:
        inside(repos.path(repo), path)
    return {"diff": repos.run(repo, "diff", *(["--cached"] if staged else []), "--", *paths)}


@mcp.tool()
async def repo_commit(repo: str, paths: list[str], message: str, push: bool = True) -> dict:
    """今回変更したファイルpathsだけをコミットする。push既定はtrue。既定ブランチへの直接保存も可能。"""
    return repos.commit(repo, paths, message, push)


@mcp.tool()
async def repo_push(repo: str) -> dict:
    """ローカルコミットを設定ブランチへpushする。前のpush失敗時もこの操作で送れる。forceは使わない。"""
    return repos.push(repo)


@mcp.tool()
async def daily_current(repo: str) -> dict:
    """設定した日報ファイルの現在の本文を返す。最新化する場合は先にrepo_syncを呼ぶ。"""
    path = repos.daily_path(repo)
    return {"path": path, "text": repos.read(repo, path), "branch": repos.branch(repo),
            "head": repos.run(repo, "rev-parse", "HEAD").strip(), "status": repos.run(repo, "status", "--short")}


@mcp.tool()
async def daily_history(repo: str, start: str, end: str, limit: int = 100,
                        clock: Literal["committer", "author"] = "committer") -> dict:
    """JSTの開始日〜終了日(YYYY-MM-DD、両端含む)で履歴を返す。clockはGit日時の選択であり作業日ではない。"""
    return repos.history(repo, start, end, bounded(limit, 1000), clock)


@mcp.tool()
async def daily_at(repo: str, commit: str) -> dict:
    """SHAで指定したコミット時点の日報本文と、Gitのauthor/committer日時・メッセージを返す。"""
    return repos.daily_at(repo, commit)


@mcp.tool()
async def daily_diff(repo: str, commit: str) -> dict:
    """SHAで指定した日報変更を返す。通常は親との差分、マージは第1親、初回は空ツリーとの差分。"""
    return repos.daily_diff(repo, commit)


@mcp.tool()
async def browser_navigate(url: str) -> dict:
    """新しいChromiumでHTTP(S)のURLへ移動する。認証値を含むURLは使えない。"""
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("認証情報を含まないHTTP(S) URLを指定してください。")
    async with browser_lock:
        page = await browser.get_page()
        response = await page.goto(url, wait_until="domcontentloaded")
        return {"url": page.url, "status": response.status if response else None, "title": await page.title()}


@mcp.tool()
async def browser_snapshot(max_chars: int = 15000) -> dict:
    """ページ本文と表示中の操作対象を返す。返されたselectorでクリック・入力する。入力値自体は列挙しない。"""
    async with browser_lock:
        return await browser.snapshot(bounded(max_chars, 100000))


@mcp.tool()
async def browser_click(selector: str) -> dict:
    """Playwright/CSS selectorで一意に選んだ要素をクリックする。"""
    async with browser_lock:
        page = await browser.get_page()
        await page.locator(selector).click()
        return {"url": page.url}


@mcp.tool()
async def browser_fill(selector: str, value: str) -> dict:
    """入力欄やcontenteditableをvalueで置き換える。秘密情報にはbrowser_fill_secretを使う。"""
    async with browser_lock:
        page = await browser.get_page()
        await page.locator(selector).fill(value)
        return {"filled": True}


@mcp.tool()
async def browser_fill_secret(selector: str, env_name: str) -> dict:
    """設定で許可した環境変数の秘密値を入力する。ツール引数・返却値に秘密値を含めない。"""
    if env_name not in config["browser"].get("secret_envs", []):
        raise ValueError("許可されていない環境変数名です。")
    value = os.environ.get(env_name)
    if not value:
        raise ValueError("秘密値が未設定です。")
    async with browser_lock:
        page = await browser.get_page()
        try:
            await page.locator(selector).fill(value)
        except PlaywrightError:
            raise ValueError("秘密値を入力できません。selectorとページの状態を確認してください。") from None
        return {"filled": True}


@mcp.tool()
async def browser_select(selector: str, values: list[str]) -> dict:
    """select要素をoptionのvalueで選ぶ。単一選択も1件の配列にする。"""
    async with browser_lock:
        page = await browser.get_page()
        return {"selected": await page.locator(selector).select_option(values)}


@mcp.tool()
async def browser_key(key: str, selector: str | None = None) -> dict:
    """Enter、Tab、Control+Aなどを送る。selector省略時は現在フォーカス中の対象へ送る。"""
    async with browser_lock:
        page = await browser.get_page()
        if selector:
            await page.locator(selector).press(key)
        else:
            await page.keyboard.press(key)
        return {"pressed": key}


@mcp.tool()
async def browser_scroll(x: int = 0, y: int = 600) -> dict:
    """ページをx/yピクセルだけスクロールする。負数で逆方向。実際の移動後座標を返す。"""
    async with browser_lock:
        page = await browser.get_page()
        await page.evaluate("p => {scrollBy(p.x,p.y)}", {"x": x, "y": y})
        return await page.evaluate("({x:scrollX,y:scrollY})")


@mcp.tool()
async def browser_boxes(selector: str) -> dict:
    """要素位置をviewport座標とページ座標で返す。撮影時はdevice_scale_factor=1。"""
    async with browser_lock:
        return await browser.boxes(selector)


@mcp.tool()
async def browser_screenshot(mode: Literal["viewport", "full_page", "element"] = "viewport",
                             selector: str | None = None, highlight_selectors: list[str] | None = None) -> list:
    """表示範囲・全体・要素を撮影する。highlight_selectorsの順に番号枠を付け、元画像も別保存する。"""
    async with browser_lock:
        return await browser.screenshot(mode, selector, highlight_selectors or [])


@mcp.tool()
async def browser_save_auth() -> dict:
    """現在のcookie・localStorage・IndexedDBを設定先に保存し、次回起動時に再利用する。状態本体は返さない。"""
    async with browser_lock:
        return await browser.save_state()


@mcp.tool()
async def browser_close() -> dict:
    """Chromiumを終了する。認証を残す場合は先にbrowser_save_authを呼ぶ。"""
    async with browser_lock:
        await browser.close()
        return {"closed": True}


@mcp.tool()
async def search_terms() -> dict:
    """人が設定した公開語IDと語句、検索対象と上限を返す。登録を変更するツールはない。"""
    return search.terms()


@mcp.tool()
async def external_search(term_ids: list[str], limit: int = 5) -> dict:
    """登録済みの公開語IDだけを組み合わせ、Tavily公式APIで一般Web検索する。自由文は受け付けない。"""
    return await search.search(term_ids, limit)


# FastMCPのツールlifespanはstateless時にはリクエスト単位になる。
# ChromiumはASGIアプリのlifespanで保持し、別のツール呼び出しへ状態を引き継ぐ。
http_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        try:
            yield
        finally:
            await browser.close()


app = Starlette(routes=[Mount("/", app=http_app)], lifespan=lifespan)


if __name__ == "__main__":
    # HTTPライブラリのINFOログにはURLが出る。通常は必要な警告だけにする。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    uvicorn.run(app, host=config["server"]["host"], port=config["server"]["port"])
