# -*- coding: utf-8 -*-
"""生成应用图标 app.ico（KS 字母标，多分辨率）。

设计：圆角方块 + 蓝色竖向渐变底 + 白色粗体 "KS" 字母标。

要点：
- 多分辨率：16/20/24/32/48/64/128/256，避免系统放大单张 16px 位图导致的锯齿
  （即"马赛克"观感）；
- 超采样绘制（8 倍后 LANCZOS 缩小），小尺寸下边缘与字形依然平滑；
- 字号按目标框自动拟合，换字体也不会溢出或过小；
- 同时写入 ``packaging/app.ico``（EXE / 安装器）与
  ``doc_tool/resources/app.ico``（开发态窗口图标）。

用法::

    python scripts/make_icon.py            # 覆盖生成两处 app.ico
    python scripts/make_icon.py --check    # 只打印现有 ICO 的尺寸清单
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
OUTPUTS = (
    REPO / "packaging" / "app.ico",
    REPO / "doc_tool" / "resources" / "app.ico",
)

TEXT = "KS"
SIZES = (16, 20, 24, 32, 48, 64, 128, 256)

# 与 UI 主题 accent 同色系（styles.py: accent #3b82f6 / accent_press #1d4ed8）
BG_TOP = (59, 130, 246)
BG_BOTTOM = (29, 78, 216)
FG = (255, 255, 255, 255)

# 候选粗体字体（按优先级），找不到则回落到 PIL 内置位图字体
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeuib.ttf",     # Segoe UI Bold
    r"C:\Windows\Fonts\seguisb.ttf",      # Segoe UI Semibold
    r"C:\Windows\Fonts\arialbd.ttf",      # Arial Bold
    r"C:\Windows\Fonts\calibrib.ttf",     # Calibri Bold
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)

SS = 8  # 超采样倍数


def _font_path() -> str | None:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def _fit_font(path: str, text: str, box_w: int, box_h: int) -> ImageFont.FreeTypeFont:
    """返回使 ``text`` 恰好填满 ``box_w`` x ``box_h`` 的字体实例。"""
    size = max(8, box_h)
    font = ImageFont.truetype(path, size)
    for _ in range(24):
        left, top, right, bottom = font.getbbox(text)
        width, height = right - left, bottom - top
        if width <= 0 or height <= 0:
            break
        scale = min(box_w / width, box_h / height)
        if 0.995 <= scale <= 1.005:
            break
        size = max(8, int(round(size * scale)))
        font = ImageFont.truetype(path, size)
    return font


def _gradient(size: int) -> Image.Image:
    """竖向线性渐变底色。"""
    grad = Image.new("RGB", (1, size))
    px = grad.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = tuple(
            int(round(a + (b - a) * t)) for a, b in zip(BG_TOP, BG_BOTTOM)
        )
    return grad.resize((size, size), Image.BILINEAR)


def _glyph(size: int) -> Image.Image:
    """绘制单个分辨率的 KS 图标（超采样后缩小）。"""
    big = size * SS

    # 圆角遮罩 —— 小尺寸下圆角比例略收，避免边角被吃掉
    radius_ratio = 0.20 if size >= 32 else 0.16
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (big - 1, big - 1)],
        radius=int(big * radius_ratio),
        fill=255,
    )

    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    img.paste(_gradient(big), (0, 0), mask)

    # 字母标：常规尺寸占 66% 宽 / 48% 高；≤24px 时适度放大以保证可读
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w_ratio, h_ratio = (0.66, 0.48) if size >= 32 else (0.76, 0.56)
    box_w, box_h = int(big * w_ratio), int(big * h_ratio)
    path = _font_path()
    if path:
        font = _fit_font(path, TEXT, box_w, box_h)
        left, top, right, bottom = font.getbbox(TEXT)
        x = (big - (right - left)) / 2 - left
        y = (big - (bottom - top)) / 2 - top - big * 0.015
        draw.text((x, y), TEXT, font=font, fill=FG)
    else:
        # 无可用 TrueType 字体时的兜底：内置位图字体居中绘制
        draw.text((big / 2, big / 2), TEXT, font=ImageFont.load_default(),
                  fill=FG, anchor="mm")

    img = Image.alpha_composite(img, layer)
    return img.resize((size, size), Image.LANCZOS)


def _check() -> int:
    for out in OUTPUTS:
        if not out.exists():
            print("missing: {0}".format(out))
            continue
        with Image.open(out) as im:
            sizes = sorted(im.ico.sizes()) if hasattr(im, "ico") else [im.size]
        print("{0}: {1}".format(out, sizes))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 KS 应用图标")
    parser.add_argument("--check", action="store_true", help="只检查现有 ICO 分辨率")
    args = parser.parse_args(argv)
    if args.check:
        return _check()

    largest = max(SIZES)
    base = _glyph(largest)
    frames = [_glyph(s) for s in SIZES if s != largest]
    for out in OUTPUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        base.save(
            str(out),
            format="ICO",
            sizes=[(s, s) for s in SIZES],
            append_images=frames,
        )
        print("wrote: {0} ({1} sizes)".format(out, len(SIZES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
