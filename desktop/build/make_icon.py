#!/usr/bin/env python
"""Generate the Momentum Lab application icon (build/icon.ico + build/icon.png).

Reproducible asset generation so the committed icon can be regenerated:

    pip install pillow
    python desktop/build/make_icon.py

Produces a multi-resolution Windows ``.ico`` (16-256 px) and a 1024 px ``.png``
(used for macOS/Linux). The mark: a deep-navy gradient tile (the app surface),
two recessive candlesticks, and a bold rising momentum stroke that sweeps from
accent blue to bull green with an arrowhead — glowing, so it stays legible on
dark and light taskbars, and simple enough to read at 16 px.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent

# Brand tokens (mirror desktop/renderer/tailwind.config.ts).
BG_TOP = (18, 28, 48)  # gradient top — a lifted navy
BG_BOTTOM = (7, 11, 20)  # gradient bottom — near-black navy
EDGE = (79, 142, 247, 70)  # faint accent border
CANDLE_UP = (5, 150, 105)  # chart.up (validated mark green)
CANDLE_DOWN = (60, 76, 104)  # recessive slate for the pullback candle
ARROW_FROM = (79, 142, 247)  # accent blue
ARROW_TO = (52, 211, 153)  # bull green
GLOW = (79, 142, 247)

S = 1024  # final size; rendered at 2x and downsampled for clean edges


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _tile(size: int) -> Image.Image:
    """Rounded gradient tile with a faint accent edge."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    for y in range(size):
        row = _lerp(BG_TOP, BG_BOTTOM, y / size)
        for x in range(size):
            px[x, y] = row + (255,)
    mask = Image.new("L", (size, size), 0)
    r = round(size * 0.22)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=255)
    img.paste(grad, (0, 0), mask)
    edge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        (size * 0.008, size * 0.008, size * 0.992, size * 0.992),
        radius=r,
        outline=EDGE,
        width=max(2, size // 170),
    )
    return Image.alpha_composite(img, edge)


def _candles(draw: ImageDraw.ImageDraw, s: float) -> None:
    """Two recessive candlesticks behind the arrow — the trading identity."""

    def candle(
        cx: float, top: float, bottom: float, color: tuple[int, int, int], alpha: int
    ) -> None:
        w = 92 * s
        wick = 18 * s
        draw.rounded_rectangle(
            (cx - wick / 2, (top - 90 * s), cx + wick / 2, (bottom + 60 * s)),
            radius=wick / 2,
            fill=color + (alpha,),
        )
        draw.rounded_rectangle(
            (cx - w / 2, top, cx + w / 2, bottom), radius=26 * s, fill=color + (alpha,)
        )

    candle(330 * s, 560 * s, 800 * s, CANDLE_DOWN, 200)
    candle(535 * s, 420 * s, 720 * s, CANDLE_UP, 185)


def _arrow_points(s: float) -> list[tuple[float, float]]:
    return [(200 * s, 745 * s), (455 * s, 560 * s), (590 * s, 650 * s), (835 * s, 335 * s)]


def _momentum_arrow(size: int) -> Image.Image:
    """The rising stroke, color-swept blue→green, with an arrowhead."""
    s = size / 1024.0
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pts = _arrow_points(s)
    width = round(86 * s)

    # Sub-segmented polyline so the color sweeps smoothly along the path.
    total = sum(
        ((pts[i + 1][0] - pts[i][0]) ** 2 + (pts[i + 1][1] - pts[i][1]) ** 2) ** 0.5
        for i in range(len(pts) - 1)
    )
    walked = 0.0
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        seg = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        steps = max(2, int(seg / (14 * s)))
        for k in range(steps):
            t0, t1 = k / steps, (k + 1) / steps
            color = _lerp(ARROW_FROM, ARROW_TO, (walked + seg * (t0 + t1) / 2) / total)
            d.line(
                (
                    x0 + (x1 - x0) * t0,
                    y0 + (y1 - y0) * t0,
                    x0 + (x1 - x0) * t1,
                    y0 + (y1 - y0) * t1,
                ),
                fill=color + (255,),
                width=width,
            )
        # Round the joints.
        d.ellipse(
            (x1 - width / 2, y1 - width / 2, x1 + width / 2, y1 + width / 2),
            fill=_lerp(ARROW_FROM, ARROW_TO, (walked + seg) / total) + (255,),
        )
        walked += seg

    # Arrowhead at the final heading.
    hx, hy = pts[-1]
    head = 150 * s
    d.polygon(
        [
            (hx + 96 * s, hy - 96 * s),
            (hx - head, hy - 8 * s),
            (hx + 10 * s, hy + head),
        ],
        fill=ARROW_TO + (255,),
    )
    return layer


def render(size: int = S) -> Image.Image:
    big = size * 2  # supersample
    img = _tile(big)
    d = ImageDraw.Draw(img)
    _candles(d, big / 1024.0)

    arrow = _momentum_arrow(big)
    glow = arrow.filter(ImageFilter.GaussianBlur(big // 34))
    img = Image.alpha_composite(img, glow)
    img = Image.alpha_composite(img, arrow)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    base = render(S)
    base.save(OUT / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(OUT / "icon.ico", sizes=[(n, n) for n in sizes])
    print(f"wrote {OUT / 'icon.png'} and {OUT / 'icon.ico'} ({sizes})")


if __name__ == "__main__":
    main()
