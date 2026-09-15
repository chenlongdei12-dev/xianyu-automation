#!/usr/bin/env python3
"""访达文件夹截图 + 顶部两行红字抬头。

用法:
  python make_cover.py --folder "/path/to/folder" \
      --line1 "XX抖音全部公开内容逐字稿" --line2 "网盘秒发" \
      [--out /path/to/out.png]
"""
import argparse
import os
import subprocess
import sys
import time

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", 2),   # W6
    ("/System/Library/Fonts/STHeiti Medium.ttc", 1),     # Heiti SC Medium
    ("/System/Library/Fonts/Supplemental/Songti.ttc", 1),
]
RED = (214, 25, 25)


def find_font(size):
    for path, idx in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size, index=idx)
            except Exception:
                continue
    raise RuntimeError("未找到可用的中文字体")


def finder_window_id(folder):
    """按文件夹名匹配访达窗口，返回 (window_id, bounds)。"""
    import Quartz

    target = os.path.basename(os.path.normpath(folder))
    wl = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    fallback = None
    for w in wl:
        if w.get("kCGWindowOwnerName") not in ("Finder", "访达"):
            continue
        if w.get("kCGWindowLayer") != 0:
            continue
        name = w.get("kCGWindowName") or ""
        wid = w.get("kCGWindowNumber")
        bounds = w.get("kCGWindowBounds")
        if target and target in name:
            return wid, bounds
        if fallback is None:
            fallback = (wid, bounds)
    if fallback:
        return fallback
    raise RuntimeError("未找到访达窗口，请确认文件夹已打开")


def capture(folder, tmp_png):
    subprocess.run(["open", folder], check=True)
    time.sleep(2.0)
    wid, bounds = finder_window_id(folder)
    subprocess.run(["screencapture", "-x", "-o", "-l%d" % wid, tmp_png], check=True)
    if not os.path.exists(tmp_png) or os.path.getsize(tmp_png) < 5000:
        raise RuntimeError("截图失败或内容为空: %s" % tmp_png)
    print("窗口 id=%s bounds=%s -> %s" % (wid, dict(bounds), tmp_png))


def add_red_overlay(src, dst, line1, line2, size1=46, size2=46,
                    stroke1=4, stroke2=4, gap=42, y_offset=24):
    """默认模式：红字直接压在截图本身上，画布尺寸与截图完全一致。

    两行默认同号（46px），行间距 42px，白色描边保证压在文件列表上仍清晰。
    """
    im = Image.open(src).convert("RGB")
    W, H = im.size
    f1, f2 = find_font(size1), find_font(size2)
    draw = ImageDraw.Draw(im)
    b1 = draw.textbbox((0, 0), line1, font=f1)
    b2 = draw.textbbox((0, 0), line2, font=f2)
    h1, h2 = b1[3] - b1[1], b2[3] - b2[1]
    top = (H - (h1 + gap + h2)) / 2 + y_offset

    def centered(text, font, box, y_top, stroke):
        x = (W - (box[2] - box[0])) / 2 - box[0]
        draw.text((x, y_top - box[1]), text, font=font, fill=RED,
                  stroke_width=stroke, stroke_fill=(255, 255, 255))

    centered(line1, f1, b1, top, stroke1)
    centered(line2, f2, b2, top + h1 + gap, stroke2)
    im.save(dst, quality=95)
    print("输出(overlay): %s %s" % (dst, im.size))


def add_red_band(src, dst, line1, line2, size1=46, size2=54):
    """备选模式：向上扩展一条白色抬头带放红字，截图完整保留在下方。"""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    f1, f2 = find_font(size1), find_font(size2)

    probe = ImageDraw.Draw(im)
    b1 = probe.textbbox((0, 0), line1, font=f1)
    b2 = probe.textbbox((0, 0), line2, font=f2)
    h1, h2 = b1[3] - b1[1], b2[3] - b2[1]
    pad_top, pad_bot, gap = 26, 30, 16
    band_h = pad_top + h1 + gap + h2 + pad_bot

    canvas = Image.new("RGB", (W, H + band_h), (255, 255, 255))
    draw = ImageDraw.Draw(canvas)

    def centered(text, font, box, y_top):
        draw.text(((W - (box[2] - box[0])) / 2 - box[0], y_top - box[1]),
                  text, font=font, fill=RED)

    centered(line1, f1, b1, pad_top)
    centered(line2, f2, b2, pad_top + h1 + gap)

    canvas.paste(im, (0, band_h))
    draw.line([(0, band_h - 1), (W, band_h - 1)], fill=(226, 226, 226), width=1)
    canvas.save(dst, quality=95)
    print("输出(band): %s %s" % (dst, canvas.size))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--line1", required=True)
    ap.add_argument("--line2", required=True)
    ap.add_argument("--out")
    ap.add_argument("--mode", choices=["overlay", "band"], default="overlay",
                    help="overlay=红字直接压在截图上（默认）；band=上方加白底抬头")
    ap.add_argument("--size1", type=int, default=46)
    ap.add_argument("--size2", type=int, default=46)
    ap.add_argument("--gap", type=int, default=42, help="两行之间的行间距（px）")
    ap.add_argument("--skip-capture", action="store_true",
                    help="跳过截图，直接对 --shot 指定的已有截图加红字")
    ap.add_argument("--shot", help="已有截图路径（配合 --skip-capture）")
    a = ap.parse_args()

    folder = os.path.abspath(a.folder)
    name = os.path.basename(os.path.normpath(folder))
    out = a.out or os.path.join(os.path.dirname(folder), "%s_红字封面.png" % name)

    if a.skip_capture:
        shot = a.shot or os.path.join(os.path.dirname(folder), "访达_%s.png" % name)
    else:
        shot = "/tmp/finder_shot_%s.png" % name
        capture(folder, shot)

    if a.mode == "overlay":
        add_red_overlay(shot, out, a.line1, a.line2, a.size1, a.size2, gap=a.gap)
    else:
        add_red_band(shot, out, a.line1, a.line2, a.size1, a.size2)


if __name__ == "__main__":
    sys.exit(main())
