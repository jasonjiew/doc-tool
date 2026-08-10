# -*- coding: utf-8 -*-
"""生成应用图标 app.ico（多分辨率）。

一次性脚本：用 Pillow 生成带「康」字标识的多尺寸 ICO。只生成缺失的
``packaging/app.ico``，已存在则跳过，避免覆盖设计稿。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "packaging" / "app.ico"

SIZES = (16, 24, 32, 48, 64, 128, 256)
BG = (56, 132, 110)       # 康尚主绿
FG = (255, 255, 255)


def _font(size: int):
    for name in (
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ):
        path = Path(name)
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                continue
    return ImageFont.load_default()


def _glyph(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=size // 6, fill=BG)
    font = _font(int(size * 0.62))
    glyph = "康"
    try:
        bbox = d.textbbox((0, 0), glyph, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x = (size - w) // 2 - bbox[0]
        y = (size - h) // 2 - bbox[1]
    except Exception:
        x = y = size // 4
    d.text((x, y), glyph, font=font, fill=FG)
    return img


def main() -> int:
    if OUT.exists():
        print("skip: {0} already exists".format(OUT))
        return 0
    images = [_glyph(s) for s in SIZES]
    images[0].save(str(OUT), format="ICO", sizes=[(s, s) for s in SIZES])
    print("wrote: {0}".format(OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
