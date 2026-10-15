
"""Render the WorkBuddy Tools logo at high resolution and package it as .icns.

Mirrors docs/logo/logo.svg at any size so the mac icon set is crisp (the repo
only ships 256px PNGs, too small for iconset's 1024px slot).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

# Repo root: this file lives in <root>/scripts/.
ROOT = Path(__file__).resolve().parents[1]


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def hgrad(size, c0, c1):
    g = Image.new("RGBA", (2, 2))
    g.putpixel((0, 0), (*c0, 255))
    g.putpixel((1, 0), (*lerp(c0, c1, 0.5), 255))
    g.putpixel((0, 1), (*lerp(c0, c1, 0.5), 255))
    g.putpixel((1, 1), (*c1, 255))
    return g.resize(size, Image.BICUBIC)


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=radius, fill=255)
    return m


def render(size):
    img = hgrad((size, size), (0x3B, 0x82, 0xF6), (0x1D, 0x4E, 0xD8)).convert("RGBA")
    img.putalpha(rounded_mask((size, size), int(size * 56 / 256)))
    d = ImageDraw.Draw(img)

    def sx(v):
        return size * v / 256.0

    white = (255, 255, 255, 255)
    d.polygon([(sx(48), sx(72)), (sx(76), sx(72)), (sx(94), sx(144)), (sx(116), sx(72)), (sx(140), sx(72)),
               (sx(88), sx(184)), (sx(64), sx(184))], fill=white)
    d.polygon([(sx(140), sx(72)), (sx(168), sx(72)), (sx(120), sx(184)), (sx(100), sx(184))], fill=white)
    d.polygon([(sx(168), sx(72)), (sx(196), sx(72)), (sx(212), sx(184)), (sx(186), sx(184))], fill=white)

    green = (0x34, 0xD3, 0x99, 255)
    d.rounded_rectangle([sx(90), sx(196), sx(174), sx(210)], radius=sx(7), fill=green)
    cx, cy, r = sx(86), sx(203), sx(14)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=green, width=max(1, int(sx(10))))
    d.rounded_rectangle([sx(172), sx(194), sx(182), sx(212)], radius=sx(3), fill=green)
    return img


def main():
    out = ROOT / "src-tauri" / "icons"
    out.mkdir(parents=True, exist_ok=True)

    render(1024).save(out / "icon_1024x1024.png")

    # iconutil requires the directory to end in .iconset
    tmp = Path(tempfile.mkdtemp(prefix="wbt-icon-"))
    iconset = tmp.with_name(tmp.name + ".iconset")
    iconset.mkdir()
    for px in (16, 32, 128, 256, 512):
        render(px).save(iconset / f"icon_{px}x{px}.png")
        render(px * 2).save(iconset / f"icon_{px}x{px}@2x.png")

    icns = out / "icon.icns"
    if icns.exists():
        icns.unlink()
    subprocess.run(["iconutil", "-c", "icns", str(iconset)], check=True)
    produced = iconset.with_suffix(".icns")
    # shutil.move: temp dir may live on a different volume than the repo.
    shutil.move(str(produced), str(icns))

    subprocess.run(["file", str(icns)], check=True)


if __name__ == "__main__":
    main()
