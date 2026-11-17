"""一回の基本動作確認。Docker内で `python -m scripts.smoke` を実行する。

実サービスの資格情報は使わない。作業用HTTPS Git・ページ・検索APIを一時起動し、
実際のStreamable HTTP接続から全ツールを呼ぶ。Tavily自体の疎通は別途行う。
"""

import asyncio
import base64
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from PIL import Image

HTML = b'''<!doctype html><html><title>Smoke</title><body>
<h1>Manual fixture</h1><input id="name" placeholder="Name"><input id="password" type="password">
<select id="select"><option value="a">A</option><option value="b">B</option></select>
<button id="save" onclick="document.querySelector('#result').textContent='saved';localStorage.setItem('login','yes')">Save</button>
<p id="result"></p><div style="height:1500px">Content</div></body></html>'''


def run(*args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True).stdout.decode().strip()


async def exercise(url: str, root: Path, fixture_url: str):
    called = set()
    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as client:
            await client.initialize()
            catalogue = await client.list_tools()

            async def call(name, args=None, error=False, image=False):
                result = await client.call_tool(name, args or {})
                assert bool(result.isError) == error, (name, result)
                called.add(name)
                if error:
                    return result
                if image:
                    content = next(c for c in result.content if c.type == "image")
                    assert content.mimeType == "image/png"
                    Image.open(io.BytesIO(base64.b64decode(content.data))).verify()
                    return json.loads(next(c.text for c in result.content if c.type == "text"))
                if result.structuredContent is not None:
                    return result.structuredContent
                return json.loads(result.content[0].text)

            await call("screenshot_list")
            await call("screenshot_get", {"path": "snip.png"}, image=True)
            await call("screenshot_latest", image=True)
            annotated = await call("image_annotate", {"source": "screenshots", "path": "snip.png",
                "marks": [{"x": 5, "y": 30, "width": 120, "height": 60, "number": 1, "label": "保存"}]}, image=True)
            assert (root / "screenshots/snip.png").read_bytes() == (root / "original.png").read_bytes()
            await call("image_get", {"source": "artifacts", "path": annotated["path"]}, image=True)
            await call("screenshot_get", {"path": "../config.toml"}, error=True)
            await call("repo_list")
            await call("repo_sync", {"repo": "knowledge"})
            await call("repo_sync", {"repo": "daily"})
            await call("repo_files", {"repo": "knowledge"})
            await call("repo_read", {"repo": "knowledge", "path": "daily.md"})
            # 別ファイルの変更が混ざらないことも確認する。
            await call("repo_write", {"repo": "knowledge", "path": "other.md", "content": "keep uncommitted"})
            await call("repo_write", {"repo": "knowledge", "path": "README.md", "content": "# Manual\n\n![save](assets/save.png)",
                                      "sources": [fixture_url]})
            await call("repo_copy_image", {"repo": "knowledge", "source": "artifacts", "path": annotated["path"], "destination": "assets/save.png"})
            await call("repo_image", {"repo": "knowledge", "path": "assets/save.png"}, image=True)
            await call("repo_status", {"repo": "knowledge"})
            await call("repo_search", {"repo": "knowledge", "text": "Manual"})
            await call("repo_diff", {"repo": "knowledge", "paths": ["daily.md"]})
            commit = await call("repo_commit", {"repo": "knowledge", "paths": ["README.md", "assets/save.png"], "message": "manual", "push": True})
            saved = run("git", "--git-dir", str(root / "remote.git"), "show", "HEAD:README.md")
            assert "参照元" in saved and commit["pushed"]
            tracked = run("git", "--git-dir", str(root / "remote.git"), "ls-tree", "--name-only", "HEAD")
            assert "other.md" not in tracked
            await call("repo_push", {"repo": "knowledge"})
            await call("repo_delete", {"repo": "knowledge", "path": "other.md"})
            await call("repo_sync", {"repo": "knowledge"})
            await call("repo_write", {"repo": "daily", "path": "daily.md", "content": "forbidden"}, error=True)
            await call("repo_write", {"repo": "knowledge", "path": ".git/config", "content": "forbidden"}, error=True)
            current = await call("daily_current", {"repo": "daily"})
            history = await call("daily_history", {"repo": "daily", "start": "2026-11-16", "end": "2026-11-16"})
            assert len(history["commits"]) == 1 and history["commits"][0]["work_date"] is None
            author = await call("daily_history", {"repo": "daily", "start": "2026-11-15", "end": "2026-11-15", "clock": "author"})
            assert len(author["commits"]) == 1
            old = await call("daily_at", {"repo": "daily", "commit": current["head"]})
            assert "task" in old["text"]
            diff = await call("daily_diff", {"repo": "daily", "commit": current["head"]})
            assert "+- [x] task" in diff["diff"]
            await call("browser_navigate", {"url": fixture_url})
            snapshot = await call("browser_snapshot")
            assert any(t["tag"] == "button" for t in snapshot["targets"])
            await call("browser_fill", {"selector": "#name", "value": "sample"})
            await call("browser_fill_secret", {"selector": "#password", "env_name": "SMOKE_SECRET"})
            await call("browser_select", {"selector": "#select", "values": ["b"]})
            await call("browser_key", {"key": "Tab", "selector": "#name"})
            await call("browser_click", {"selector": "#save"})
            assert "saved" in (await call("browser_snapshot"))["text"]
            await call("browser_boxes", {"selector": "#save"})
            shot = await call("browser_screenshot", {"highlight_selectors": ["#save"]}, image=True)
            assert shot["original"]["path"] != shot["path"] and len(shot["marks"]) == 1
            (root / "preview.png").write_bytes((root / "artifacts" / shot["path"]).read_bytes())
            await call("browser_scroll", {"y": 200})
            await call("browser_screenshot", {"mode": "full_page", "highlight_selectors": ["#save"]}, image=True)
            await call("browser_screenshot", {"mode": "element", "selector": "#save", "highlight_selectors": ["#save"]}, image=True)
            await call("browser_save_auth")
            assert "yes" in (root / "browser/auth.json").read_text()
            await call("browser_close")
            await call("browser_navigate", {"url": fixture_url})
            await call("browser_save_auth")
            assert "yes" in (root / "browser/auth.json").read_text()
            await call("browser_close")
            await call("search_terms")
            results = await call("external_search", {"term_ids": ["python", "playwright"], "limit": 1})
            assert results["query"] == "Python Playwright" and len(results["results"]) == 1
            await call("external_search", {"term_ids": ["unregistered internal question"]}, error=True)
            (root / "repos/knowledge/escape").symlink_to(root / "browser", target_is_directory=True)
            await call("repo_read", {"repo": "knowledge", "path": "escape/auth.json"}, error=True)
            names = {tool.name for tool in catalogue.tools}
            assert names == called, (names - called, called - names)
            print(json.dumps({"tools_called": len(called), "transport": "streamable-http", "image_content": "PNG verified",
                              "git": "HTTPS Basic clone/commit/push verified", "search": "local API fixture only"}, ensure_ascii=False))


def main():
    with TemporaryDirectory(prefix="mcp-smoke-") as temp:
        root = Path(temp)
        for part in ("screenshots", "artifacts", "repos", "browser", "seed"):
            (root / part).mkdir()
        Image.new("RGB", (640, 320), "#f0f0f0").save(root / "screenshots/snip.png")
        shutil.copyfile(root / "screenshots/snip.png", root / "original.png")
        run("git", "init", "--bare", "--initial-branch=main", str(root / "remote.git"))
        run("git", "--git-dir", str(root / "remote.git"), "config", "http.receivepack", "true")
        run("git", "init", "--initial-branch=main", str(root / "seed"))
        (root / "seed/daily.md").write_text("- [x] task\n", encoding="utf-8")
        run("git", "add", "daily.md", cwd=root / "seed")
        env = {**os.environ, "GIT_AUTHOR_DATE": "2026-11-15T00:30:00+09:00", "GIT_COMMITTER_DATE": "2026-11-16T00:30:00+09:00"}
        run("git", "-c", "user.name=Smoke", "-c", "user.email=smoke@example.invalid", "commit", "-m", "2026-11-16 memo", cwd=root / "seed", env=env)
        run("git", "push", str(root / "remote.git"), "main", cwd=root / "seed")
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(root / "key.pem"),
            "-out", str(root / "cert.pem"), "-days", "1", "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1")
        queries = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.startswith("/remote.git/"):
                    return self.git()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(HTML)))
                self.end_headers()
                self.wfile.write(HTML)

            def do_POST(self):
                if self.path.startswith("/remote.git/"):
                    return self.git()
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert self.headers["Authorization"] == "Bearer fixture-key"
                assert body["include_answer"] is False and body["search_depth"] == "basic"
                queries.append(body["query"])
                data = json.dumps({"results": [{"title": "Fixture", "url": "https://example.org", "content": "snippet", "score": 1}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def git(self):
                if self.headers.get("Authorization") != "Basic " + base64.b64encode(b"smoke:fixture-password").decode():
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="smoke"')
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                parsed = urlsplit(self.path)
                env = {**os.environ, "GIT_PROJECT_ROOT": str(root), "GIT_HTTP_EXPORT_ALL": "1",
                       "PATH_INFO": parsed.path, "QUERY_STRING": parsed.query, "REQUEST_METHOD": self.command,
                       "CONTENT_TYPE": self.headers.get("Content-Type", ""), "REMOTE_USER": "smoke"}
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length) if length else b""
                output = subprocess.run(["git", "http-backend"], input=body, env=env, capture_output=True, check=True).stdout
                headers, data = output.split(b"\r\n\r\n", 1)
                pairs = [line.decode().split(": ", 1) for line in headers.split(b"\r\n")]
                status = next((int(value.split()[0]) for name, value in pairs if name == "Status"), 200)
                self.send_response(status)
                for name, value in pairs:
                    if name != "Status":
                        self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        fixture = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        git_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(root / "cert.pem", root / "key.pem")
        git_server.socket = context.wrap_socket(git_server.socket, server_side=True)
        for server in (fixture, git_server):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        fixture_url = f"http://127.0.0.1:{fixture.server_port}"
        git_url = f"https://127.0.0.1:{git_server.server_port}/remote.git"
        template = Path("/app/config/config.example.toml")
        if not template.exists():
            template = Path(__file__).resolve().parents[1] / "config/config.example.toml"
        config = template.read_text().replace("/screenshots", str(root / "screenshots")).replace("/data/", f"{root}/")
        config = config.replace("https://gitea.example.internal/YOUR_NAME/knowledge.git", git_url)
        config = config.replace("https://gitea.example.internal/YOUR_NAME/daily.git", git_url)
        config = config.replace("https://api.tavily.com/search", fixture_url + "/search")
        config = config.replace('["INTRANET_USERNAME", "INTRANET_PASSWORD"]', '["SMOKE_SECRET"]')
        # 固定ポートはこのコンテナ内だけで使用する。
        config = config.replace('host = "0.0.0.0"', 'host = "127.0.0.1"')
        (root / "config.toml").write_text(config)
        env = {**os.environ, "MCP_CONFIG": str(root / "config.toml"), "GITEA_USERNAME": "smoke", "GITEA_PASSWORD": "fixture-password",
               "GIT_SSL_CAINFO": str(root / "cert.pem"), "TAVILY_API_KEY": "fixture-key", "SMOKE_SECRET": "fixture-secret"}
        for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
            env.pop(name, None)
        env["no_proxy"] = env["NO_PROXY"] = "127.0.0.1,localhost"
        log = root / "server.log"
        with log.open("w") as output:
            process = subprocess.Popen([sys.executable, "-m", "app.server"], env=env, stdout=output, stderr=output)
            try:
                # 起動待ちだけの短い確認。製品側にリトライ機構は設けない。
                import time
                with httpx.Client(trust_env=False) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError(log.read_text())
                        try:
                            if client.get("http://127.0.0.1:8000/health").is_success:
                                break
                        except httpx.ConnectError:
                            pass
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("MCP起動待ちがタイムアウトしました。")
                asyncio.run(exercise("http://127.0.0.1:8000/mcp", root, fixture_url))
                assert queries == ["Python Playwright"], queries
                if os.environ.get("SMOKE_PREVIEW_DIR"):
                    shutil.copyfile(root / "preview.png", Path(os.environ["SMOKE_PREVIEW_DIR"]) / "smoke-browser.png")
                    shutil.copyfile(root / "repos/knowledge/assets/save.png", Path(os.environ["SMOKE_PREVIEW_DIR"]) / "smoke-annotation.png")
            finally:
                process.terminate()
                process.wait(timeout=10)
                text = log.read_text()
                assert "fixture-password" not in text and "fixture-key" not in text
                fixture.shutdown()
                git_server.shutdown()


if __name__ == "__main__":
    main()
