"""画像を読み取り、別ファイルへ注釈を保存する。元画像は変更しない。"""

import io
import json
from pathlib import Path
from typing import Literal
from uuid import uuid4

from mcp.server.fastmcp import Image
from mcp.types import TextContent
from PIL import Image as PILImage, ImageDraw, ImageFont
from pydantic import BaseModel, Field

from .common import inside, iso_jst

FORMATS = {".png", ".jpg", ".jpeg", ".webp"}


class Mark(BaseModel):
    """画像左上からのピクセル座標。numberとlabelは省略できる。"""
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    number: int | None = Field(default=None, ge=1)
    label: str = Field(default="", max_length=40)
    color: str = "#e53935"


class Images:
    def __init__(self, config: dict):
        self.roots = {key: Path(config["paths"][key]) for key in ("screenshots", "artifacts")}
        self.roots["artifacts"].mkdir(parents=True, exist_ok=True)
        self.font = config["browser"]["font"]

    def path(self, source: Literal["screenshots", "artifacts"], path: str) -> Path:
        target = inside(self.roots[source], path)
        if target.suffix.lower() not in FORMATS:
            raise ValueError("PNG、JPEG、WebPを指定してください。")
        return target

    def new_path(self, prefix: str) -> Path:
        return self.roots["artifacts"] / f"{prefix}-{uuid4().hex[:12]}.png"

    def metadata(self, path: Path, source: str, root: Path | None = None) -> dict:
        with PILImage.open(path) as im:
            width, height = im.size
        return {"source": source, "path": path.relative_to(root or self.roots[source]).as_posix(),
                "filename": path.name, "saved_at_jst": iso_jst(path.stat().st_mtime),
                "saved_at_basis": "filesystem mtime", "width": width, "height": height}

    def recent(self, limit: int) -> list[dict]:
        root = self.roots["screenshots"]
        files = []
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in FORMATS:
                inside(root, path.relative_to(root).as_posix())
                files.append(path)
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [self.metadata(p, "screenshots") for p in files[:limit]]

    def content(self, path: Path, source: str, root: Path | None = None, **extra) -> list:
        # MCPのImageContentへ変換する。ファイルパスだけを返さない。
        with PILImage.open(path) as im:
            data = io.BytesIO()
            im.convert("RGB").save(data, format="PNG")
        return [TextContent(type="text", text=json.dumps({**self.metadata(path, source, root), **extra}, ensure_ascii=False)),
                Image(data=data.getvalue(), format="png")]

    def annotate(self, original: Path, marks: list[Mark]) -> Path:
        with PILImage.open(original) as im:
            canvas = im.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.truetype(self.font, 22)
        for mark in marks:
            x, y, right, bottom = mark.x, mark.y, mark.x + mark.width, mark.y + mark.height
            if right > canvas.width or bottom > canvas.height:
                raise ValueError("矩形が画像の範囲を超えています。画像のwidth/heightを確認してください。")
            draw.rectangle((x, y, right - 1, bottom - 1), outline=mark.color, width=4)
            label = " ".join(str(v) for v in (mark.number, mark.label) if v is not None and v != "")
            if label:
                bbox = draw.textbbox((0, 0), label, font=font)
                w, h = bbox[2] - bbox[0] + 12, bbox[3] - bbox[1] + 10
                tx, ty = max(0, min(x, canvas.width - w)), max(0, y - h)
                draw.rectangle((tx, ty, tx + w, ty + h), fill=mark.color)
                draw.text((tx + 6, ty + 5 - bbox[1]), label, fill="white", font=font)
        output = self.new_path("annotated")
        canvas.save(output)
        return output
