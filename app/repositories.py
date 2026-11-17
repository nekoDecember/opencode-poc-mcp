"""登録したHTTPSリポジトリだけを扱う、薄いGitラッパー。"""

from datetime import date, datetime, time, timedelta
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from .common import JST, inside


class Repositories:
    def __init__(self, config: dict):
        self.config = config
        self.root = Path(config["paths"]["repos"])
        self.root.mkdir(parents=True, exist_ok=True)
        # shebangで起動するため実行権限が必要。コード自体は書き換えない。
        self.askpass = Path(__file__).with_name("git_askpass.py")
        for name, spec in config.get("repositories", {}).items():
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                raise ValueError("リポジトリIDは英数字、_、-だけにしてください。")
            url = urlsplit(spec["url"])
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError("認証情報を含まないHTTPSのGit URLを設定してください。")

    def spec(self, repo: str) -> dict:
        return self.config["repositories"][repo]

    def path(self, repo: str) -> Path:
        self.spec(repo)
        return inside(self.root, repo)

    def run(self, repo: str, *args: str, cwd: Path | None = None, ok=(0,)) -> str:
        spec = self.spec(repo)
        env = os.environ.copy()
        # GIT_TRACE等で認証ヘッダーが漏れないよう、Gitの診断出力設定を除く。
        for key in list(env):
            if key.startswith("GIT_") and key not in ("GIT_SSL_CAINFO", "GIT_SSL_CAPATH"):
                env.pop(key)
        env.update({
            "GIT_ASKPASS": str(self.askpass), "GIT_TERMINAL_PROMPT": "0",
            "GIT_LITERAL_PATHSPECS": "1", "TZ": "Asia/Tokyo",
            "MCP_GIT_USERNAME": os.environ.get(spec.get("username_env", ""), ""),
            "MCP_GIT_PASSWORD": os.environ.get(spec.get("password_env", ""), ""),
        })
        result = subprocess.run(
            ["git", "-c", "credential.helper=", "-c", "core.hooksPath=/dev/null",
             "-c", "http.followRedirects=false", *args],
            cwd=cwd or self.path(repo), env=env, capture_output=True,
            timeout=self.config["git"].get("timeout_seconds", 120),
        )
        if result.returncode not in ok:
            # stderrにはサーバー由来の文字列も入るため、MCPやログへ転送しない。
            raise ValueError(f"Git操作({args[0]})に失敗しました。終了コード: {result.returncode}。接続・認証・ブランチ・競合を確認してください。")
        return result.stdout.decode("utf-8", errors="replace")

    def sync(self, repo: str) -> dict:
        """最初はclone、以後は作業ツリーがきれいな場合だけfast-forwardする。"""
        spec, path = self.spec(repo), self.path(repo)
        if not path.exists():
            args = ["clone", "--origin", "origin"]
            if spec.get("branch"):
                args += ["--branch", spec["branch"]]
            self.run(repo, *args, "--", spec["url"], str(path), cwd=self.root)
        else:
            self.check_branch(repo)
            self.check_origin(repo)
            if self.run(repo, "status", "--porcelain"):
                raise ValueError("未コミットの変更があります。先に保存内容を確認してコミットしてください。")
            branch = self.branch(repo)
            self.run(repo, "fetch", "origin", f"refs/heads/{branch}")
            self.run(repo, "merge", "--ff-only", "FETCH_HEAD")
        return self.status(repo)

    def branch(self, repo: str) -> str:
        return self.run(repo, "symbolic-ref", "--short", "HEAD").strip()

    def check_branch(self, repo: str) -> None:
        expected = self.spec(repo).get("branch")
        if expected and self.branch(repo) != expected:
            raise ValueError("チェックアウト中のブランチが設定と異なります。")

    def check_origin(self, repo: str) -> None:
        if self.run(repo, "remote", "get-url", "origin").strip() != self.spec(repo)["url"]:
            raise ValueError("originが設定と異なります。作業コピーを確認してください。")

    def writable(self, repo: str) -> None:
        if not self.spec(repo).get("writable", False):
            raise ValueError("このリポジトリは参照専用です。")
        self.check_branch(repo)

    def status(self, repo: str) -> dict:
        return {"repo": repo, "branch": self.branch(repo),
                "status": self.run(repo, "status", "--short"),
                "staged_diff": self.run(repo, "diff", "--cached", "--stat")}

    def files(self, repo: str, directory: str = ".", limit: int = 300) -> dict:
        root = self.path(repo)
        folder = inside(root, directory, allow_root=True)
        found = []
        for path in sorted(folder.rglob("*")):
            rel = path.relative_to(root).as_posix()
            if ".git" in path.relative_to(root).parts or path.is_symlink() or not path.is_file():
                continue
            inside(root, rel)
            found.append(rel)
            if len(found) > limit:
                break
        return {"files": found[:limit], "truncated": len(found) > limit}

    def read(self, repo: str, path: str) -> str:
        return inside(self.path(repo), path).read_text(encoding="utf-8")

    def write(self, repo: str, path: str, content: str) -> dict:
        self.writable(repo)
        target = inside(self.path(repo), path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"repo": repo, "path": path, "bytes": target.stat().st_size}

    def search(self, repo: str, text: str, limit: int = 100) -> dict:
        # 正規表現ではなく固定文字列。Git管理外の新規ファイルも対象にする。
        matches = []
        files = self.files(repo, limit=10000)
        for path in files["files"]:
            try:
                content = self.read(repo, path)
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if text.casefold() in line.casefold():
                    matches.append({"path": path, "line": number, "text": line})
                    if len(matches) >= limit:
                        return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": files["truncated"]}

    def commit(self, repo: str, paths: list[str], message: str, push: bool) -> dict:
        self.writable(repo)
        if not paths or not message.strip():
            raise ValueError("コミットするファイルとメッセージを指定してください。")
        normalized = []
        for path in paths:
            target = inside(self.path(repo), path)
            relative = target.relative_to(self.path(repo)).as_posix()
            if target.is_dir() or (not target.is_file() and
                    self.run(repo, "ls-files", "--", relative).splitlines() != [relative]):
                raise ValueError("コミット対象はファイル単位で指定してください。削除済みの管理対象ファイルも指定できます。")
            normalized.append(relative)
        paths = normalized
        # 他のstage済み変更があれば停止し、今回の指定ファイルだけをコミットする。
        if self.run(repo, "diff", "--cached", "--name-only"):
            raise ValueError("既にstage済みの変更があります。repo_statusで確認してください。")
        self.run(repo, "add", "--", *paths)
        if not self.run(repo, "diff", "--cached", "--name-only"):
            return {"committed": False, "reason": "変更はありません。"}
        git = self.config["git"]
        self.run(repo, "-c", f"user.name={git['author_name']}", "-c", f"user.email={git['author_email']}",
                 "commit", "-m", message)
        sha = self.run(repo, "rev-parse", "HEAD").strip()
        # push失敗時もローカルコミットは残る。repo_pushだけで再送できる。
        if push:
            self.push(repo)
        return {"committed": True, "commit": sha, "pushed": push, "paths": paths}

    def push(self, repo: str) -> dict:
        self.writable(repo)
        self.check_origin(repo)
        branch = self.branch(repo)
        self.run(repo, "push", "origin", f"HEAD:refs/heads/{branch}")
        return {"pushed": True, "branch": branch}

    def daily_path(self, repo: str) -> str:
        path = self.spec(repo)["daily_file"]
        inside(self.path(repo), path)
        return path

    def revision(self, repo: str, commit: str) -> str:
        if not re.fullmatch(r"[0-9a-fA-F]{4,40}", commit):
            raise ValueError("コミットのSHAを指定してください。")
        return self.run(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").strip()

    def history(self, repo: str, start: str, end: str, limit: int, clock: str) -> dict:
        """日付はJSTの両端を含む。Gitの--sinceではなく列挙後の比較で順不同日時も扱う。"""
        first = datetime.combine(date.fromisoformat(start), time.min, JST)
        until = datetime.combine(date.fromisoformat(end) + timedelta(days=1), time.min, JST)
        if until <= first or clock not in ("committer", "author"):
            raise ValueError("期間とclock(authorまたはcommitter)を確認してください。")
        path = self.daily_path(repo)
        shas = self.run(repo, "log", "--format=%H", "HEAD", "--", path).splitlines()
        entries = []
        for sha in shas:
            entry = self.metadata(repo, sha)
            value = entry[f"{clock}_at_jst"]
            if first <= datetime.fromisoformat(value) < until:
                entries.append(entry)
                if len(entries) > limit:
                    break
        return {"commits": entries[:limit], "truncated": len(entries) > limit,
                "timezone": "Asia/Tokyo", "filter_clock": clock,
                "work_date": "本文とメッセージからOpenCodeが判断する。Git日時は実際の作業日を保証しない。"}

    def metadata(self, repo: str, sha: str) -> dict:
        raw = self.run(repo, "show", "-s", "--format=%H%x00%aI%x00%cI%x00%B", sha)
        commit, author, committer, message = raw.split("\0", 3)
        return {"commit": commit, "author_at_jst": datetime.fromisoformat(author).astimezone(JST).isoformat(),
                "committer_at_jst": datetime.fromisoformat(committer).astimezone(JST).isoformat(),
                "message": message.rstrip("\n"), "work_date": None}

    def daily_at(self, repo: str, commit: str) -> dict:
        sha, path = self.revision(repo, commit), self.daily_path(repo)
        return {**self.metadata(repo, sha), "path": path,
                "text": self.run(repo, "show", f"{sha}:{path}")}

    def daily_diff(self, repo: str, commit: str) -> dict:
        sha, path = self.revision(repo, commit), self.daily_path(repo)
        parents = self.run(repo, "show", "-s", "--format=%P", sha).split()
        # 第1親を明示して、マージコミットでも比較対象を曖昧にしない。
        diff = (self.run(repo, "diff", parents[0], sha, "--", path) if parents else
                self.run(repo, "diff-tree", "--root", "--no-commit-id", "-p", sha, "--", path))
        return {**self.metadata(repo, sha), "path": path, "parent": parents[0] if parents else None, "diff": diff}
