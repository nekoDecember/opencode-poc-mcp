"""設定、時刻、保存範囲の確認。"""

import os
from datetime import datetime
from pathlib import Path
import tomllib
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def load_config() -> dict:
    with open(os.environ.get("MCP_CONFIG", "/config/config.toml"), "rb") as f:
        return tomllib.load(f)


def inside(root: Path, relative: str, *, allow_root: bool = False) -> Path:
    """絶対パス、範囲外、.git、シンボリックリンク経由のアクセスを拒否する。"""
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or any(p.casefold() == ".git" for p in rel.parts):
        raise ValueError("保存範囲内の相対パスを指定してください。.gitと..は指定できません。")
    root = root.resolve()
    target = root / rel
    current = root
    for part in rel.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("シンボリックリンクは扱いません。")
    if not target.resolve().is_relative_to(root) or (target == root and not allow_root):
        raise ValueError("保存範囲外または空のパスです。")
    return target


def iso_jst(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, JST).isoformat()


def normalize_proxy_env() -> None:
    """Python/Git/子プロセスで、小文字優先の同じproxy値を使う。"""
    for key in ("http_proxy", "https_proxy", "no_proxy"):
        value = os.environ.get(key) or os.environ.get(key.upper(), "")
        if value:
            os.environ[key] = os.environ[key.upper()] = value
