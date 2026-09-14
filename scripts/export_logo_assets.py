from pathlib import Path

import cairosvg
from PIL import Image

ROOT = Path(r"E:\workbuddy-tools")
SVG = ROOT / "docs" / "logo" / "logo.svg"
ICONS = ROOT / "src-tauri" / "icons"
UI_ASSETS = ROOT / "ui" / "src" / "assets"

ICONS.mkdir(parents=True, exist_ok=True)
UI_ASSETS.mkdir(parents=True, exist_ok=True)

for name, size in [
    ("32x32.png", 32),
    ("128x128.png", 128),
    ("128x128@2x.png", 256),
]:
    cairosvg.svg2png(
        url=str(SVG),
        write_to=str(ICONS / name),
        output_width=size,
        output_height=size,
    )
    print("icon", name, size)

im = Image.open(ICONS / "128x128@2x.png").convert("RGBA")
im.save(
    ICONS / "icon.ico",
    sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("ico ok")

# keep UI brand in sync with A1
(UI_ASSETS / "logo.svg").write_text(SVG.read_text(encoding="utf-8"), encoding="utf-8")
print("ui logo synced")

