# -*- coding: utf-8 -*-
"""生成应用图标 app.ico（多分辨率）。

一次性脚本：用 Pillow 生成中性文档图标的多样式 ICO（不含公司品牌字符）。
只生成缺失的 ``packaging/app.ico``，已存在则跳过，避免覆盖设计稿。

注：图标最终设计仍需权利人授权（见发布决策登记表），此处仅提供中性占位。
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "packaging" / "app.ico"

SIZES = (16, 24, 32, 48, 64, 128, 256)
BG = (56, 132, 110)       # 应用主色（绿）
FG = (255, 255, 255)
LINE = (40, 96, 80)       # 内嵌线条色


def _glyph(size: int) -> Image.Image:
    """绘制中性文档图标：圆角方块 + 折叠页面 + 三行文字线。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=size // 6, fill=BG)

    # 页面主体（略小的白色圆角矩形）
    page_x = int(size * 0.18)
    page_y = int(size * 0.16)
    page_w = int(size * 0.64)
    page_h = int(size * 0.68)
    page_r = max(2, size // 16)
    d.rounded_rectangle(
        [(page_x, page_y), (page_x + page_w, page_y + page_h)],
        radius=page_r,
        fill=FG,
    )

    # 折角（右上角三角形缺口，用主色填充）
    fold = int(size * 0.22)
    d.polygon(
        [
            (page_x + page_w - fold, page_y),
            (page_x + page_w, page_y),
            (page_x + page_w, page_y + fold),
        ],
        fill=BG,
    )

    # 三行文字线
    line_w = int(size * 0.40)
    line_x = page_x + int(size * 0.10)
    y0 = page_y + int(size * 0.20)
    line_h = max(1, size // 28)
    for i in range(3):
        y = y0 + i * int(size * 0.14)
        if i == 2:
            w = int(line_w * 0.7)
        else:
            w = line_w
        d.rounded_rectangle(
            [(line_x, y), (line_x + w, y + line_h)],
            radius=line_h // 2,
            fill=LINE,
        )
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
