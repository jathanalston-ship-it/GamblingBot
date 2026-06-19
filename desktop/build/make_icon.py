#!/usr/bin/env python
"""Generate the Momentum Lab application icon (build/icon.ico + build/icon.png).

Reproducible asset generation so the committed icon can be regenerated:

    pip install pillow
    python desktop/build/make_icon.py

Produces a multi-resolution Windows ``.ico`` (16-256 px) and a 1024 px ``.png``
(used for macOS/Linux and the renderer favicon). The mark is an upward
"momentum" bar chart with an arrow on the app's dark navy background.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent
BG = (11, 18, 32)  # #0b1220 — the app background
PANEL = (17, 27, 46)
BARS = [(56, 189, 248), (45, 212, 191), (34, 197, 94)]  # sky → teal → green
ARROW = (134, 239, 172)  # light green
SIZE = 1024


def _rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], r: int, fill: object) -> None:
    draw.rounded_rectangle(box, radius=r, fill=fill)


def render(size: int = SIZE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 1024.0  # scale factor

    # App tile with a subtle inner panel.
    _rounded(d, (0, 0, size, size), int(224 * s), BG + (255,))
    margin = int(120 * s)
    _rounded(d, (margin, margin, size - margin, size - margin), int(140 * s), PANEL + (255,))

    # Ascending bars (the momentum motif).
    base_y = int(760 * s)
    heights = [int(180 * s), int(300 * s), int(440 * s)]
    bar_w = int(150 * s)
    gap = int(60 * s)
    total_w = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (size - total_w) // 2
    for h, color in zip(heights, BARS, strict=True):
        _rounded(d, (x, base_y - h, x + bar_w, base_y), int(36 * s), color + (255,))
        x += bar_w + gap

    # Upward arrow over the bars.
    ax0, ay0 = int(300 * s), int(560 * s)
    ax1, ay1 = int(724 * s), int(300 * s)
    d.line((ax0, ay0, ax1, ay1), fill=ARROW + (255,), width=int(46 * s))
    head = int(70 * s)
    d.polygon(
        [
            (ax1 + int(20 * s), ay1 - int(20 * s)),
            (ax1 - head, ay1 + int(6 * s)),
            (ax1 + int(6 * s), ay1 + head),
        ],
        fill=ARROW + (255,),
    )
    return img


def main() -> None:
    base = render(SIZE)
    base.save(OUT / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(OUT / "icon.ico", sizes=[(n, n) for n in sizes])
    print(f"wrote {OUT / 'icon.png'} and {OUT / 'icon.ico'} ({sizes})")


if __name__ == "__main__":
    main()
