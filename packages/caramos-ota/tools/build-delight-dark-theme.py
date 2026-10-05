#!/usr/bin/env python3
"""Generate usr/share/themes/Cinnamon-Delight-Dark, the dark counterpart of Cinnamon-Delight.

Cinnamon-Delight (the CaramOS light theme) and Mint-Relaxed are the light and dark editions of the same
design by DrMcC0y: their CSS is structurally the same, but Mint-Relaxed paints its greys navy (OKLCH hue
~255-275) while Delight uses warm mauve greys (hue ~340). This tool takes Mint-Relaxed's dark widget
states and assets and re-tints every grey to Delight's hue, keeping each colour's lightness (so the
dark design's contrast is untouched) and leaving accents and status colours (aqua, red, green, orange)
alone. It then appends the dark three-dock panel CSS.

Usage:
  ./tools/build-delight-dark-theme.py                  # clone the pinned Mint-Relaxed commit
  ./tools/build-delight-dark-theme.py --source DIR     # use an existing Mint-Relaxed checkout

The output is committed; re-run this after changing the palette or the pinned upstream commit.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - build-time tool
    sys.exit("Pillow is required: sudo apt install python3-pil")

PKG_DIR = Path(__file__).resolve().parents[1]
OUTPUT = PKG_DIR / "usr/share/themes/Cinnamon-Delight-Dark"
DARK_DOCK_CSS = PKG_DIR / "tools/delight-dark-dock.css"
UPSTREAM_URL = "https://github.com/DrMcC0y/Mint-Relaxed.git"
UPSTREAM_COMMIT = "01c6cb9dc1679b9ecd76fdca27ab6ed99da6dffa"
THEME_NAME = "Cinnamon-Delight-Dark"

# Delight's neutrals sit at OKLCH hue 335-345 with low chroma (backgrounds ~0.006, text up to ~0.04).
DELIGHT_HUE = 340.0
TINT_CHROMA = 0.022  # peak chroma of the tint, reached at mid lightness
NEUTRAL_MAX_CHROMA = 0.06  # anything more colourful is an accent or status colour and is kept

# Mint-Relaxed paints content, toolbar band, sidebar and window background almost the same dark grey,
# while Delight separates them (content white, sidebar ~4% darker, toolbar band ~8% darker). These
# OKLCH lightness values mirror Delight's steps around a dark content area. Keys are Mint-Relaxed's
# own @define-color names; the comments name the Delight colour with the same role.
ROLE_LIGHTNESS = {
    "theme_bg_color": 0.205,  # white_bg: Nemo file area, lists, entries
    "theme_base_color": 0.255,  # nemo_side_panel_bg_color: Nemo sidebar
    "theme_base_color_lighter": 0.240,  # gray_light_bg: window background
    "dark_gray_main": 0.290,  # theme_main_bg_1: titlebar and toolbar band
    "pathbar_color": 0.345,  # primary_button_bg / nemo_path: buttons on the band
    "border_dark": 0.335,  # gray_light: borders
}

HEX_RE = re.compile(r"(?<![\w(])#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
RGB_RE = re.compile(r"\brgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(,\s*[0-9.]+\s*)?\)")
TEXT_SUFFIXES = {".css", ".rc", ".svg", ".theme", ".xml"}
TEXT_NAMES = {"gtkrc", "themerc"}


# ---- colour maths (OKLab / OKLCH, D65 sRGB) -----------------------------------------------------
def _to_linear(channel: int) -> float:
    value = channel / 255.0
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _to_srgb(value: float) -> int:
    value = min(1.0, max(0.0, value))
    encoded = 12.92 * value if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055
    return min(255, max(0, round(encoded * 255)))


def rgb_to_oklch(r: int, g: int, b: int) -> tuple[float, float, float]:
    lr, lg, lb = _to_linear(r), _to_linear(g), _to_linear(b)
    l = (0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb) ** (1 / 3)
    m = (0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb) ** (1 / 3)
    s = (0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb) ** (1 / 3)
    lightness = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return lightness, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def oklch_to_rgb(lightness: float, chroma: float, hue: float) -> tuple[int, int, int]:
    a = chroma * math.cos(math.radians(hue))
    bb = chroma * math.sin(math.radians(hue))
    l = (lightness + 0.3963377774 * a + 0.2158037573 * bb) ** 3
    m = (lightness - 0.1055613458 * a - 0.0638541728 * bb) ** 3
    s = (lightness - 0.0894841775 * a - 1.2914855480 * bb) ** 3
    return (
        _to_srgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
        _to_srgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
        _to_srgb(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s),
    )


def retint(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Give a grey Delight's hue at the same lightness; keep accent and status colours."""

    lightness, chroma, _hue = rgb_to_oklch(r, g, b)
    if chroma >= NEUTRAL_MAX_CHROMA:
        return r, g, b
    # Fades to zero at black and white, so shadows stay black and pure highlights stay white.
    tint = TINT_CHROMA * 4 * lightness * (1 - lightness)
    return oklch_to_rgb(lightness, tint, DELIGHT_HUE)


# ---- file rewriting ------------------------------------------------------------------------------
def _hex(match: re.Match[str]) -> str:
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
    nr, ng, nb = retint(r, g, b)
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _rgb(match: re.Match[str]) -> str:
    r, g, b = (int(match.group(i)) for i in (1, 2, 3))
    nr, ng, nb = retint(r, g, b)
    alpha = match.group(4)
    if alpha:
        return f"rgba({nr}, {ng}, {nb}, {alpha.strip(', ').strip()})"
    return f"rgb({nr}, {ng}, {nb})"


def retint_text(text: str) -> str:
    return RGB_RE.sub(_rgb, HEX_RE.sub(_hex, text))


def retint_css(text: str) -> str:
    """Recolour declaration values and @define-color lines, never selectors such as #panel."""

    out: list[str] = []
    depth = 0
    position = 0
    for match in re.finditer(r"[{}]|@define-color[^;]*;", text):
        chunk = text[position:match.start()]
        out.append(retint_text(chunk) if depth > 0 else chunk)
        token = match.group(0)
        if token == "{":
            depth += 1
            out.append(token)
        elif token == "}":
            depth = max(0, depth - 1)
            out.append(token)
        else:
            out.append(retint_text(token))
        position = match.end()
    tail = text[position:]
    out.append(retint_text(tail) if depth > 0 else tail)
    return "".join(out)


def tinted(lightness: float) -> str:
    r, g, b = oklch_to_rgb(lightness, TINT_CHROMA * 4 * lightness * (1 - lightness), DELIGHT_HUE)
    return f"#{r:02x}{g:02x}{b:02x}"


def apply_role_lightness(css: str) -> str:
    for name, lightness in ROLE_LIGHTNESS.items():
        css, count = re.subn(
            rf"^@define-color {name} [^;]+;",
            f"@define-color {name} {tinted(lightness)};",
            css,
            count=1,
            flags=re.M,
        )
        if count != 1:
            raise SystemExit(f"Mint-Relaxed no longer defines @{name}; update ROLE_LIGHTNESS")
    return css


def retint_png(path: Path) -> None:
    if path.stat().st_size == 0:
        return  # upstream ships a few empty "*-2.png" leftovers; keep them as they are
    with Image.open(path) as source:
        mode = source.mode
        image = source.convert("RGBA")
    cache: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b, a = pixels[x, y]
            if a == 0:
                continue
            key = (r, g, b)
            if key not in cache:
                cache[key] = retint(r, g, b)
            pixels[x, y] = (*cache[key], a)
    if mode == "P":
        image = image.convert("RGBA")
    image.save(path, optimize=True)


def build(source: Path) -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    shutil.copytree(source, OUTPUT, ignore=shutil.ignore_patterns(".git", ".gitignore"))
    (OUTPUT / "README.md").rename(OUTPUT / "README.Mint-Relaxed.md")

    shell_css = OUTPUT / "cinnamon/cinnamon.css"
    shell = shell_css.read_text(encoding="utf-8").rstrip()
    shell_css.write_text(shell + "\n\n" + DARK_DOCK_CSS.read_text(encoding="utf-8").strip() + "\n", encoding="utf-8")

    for path in sorted(OUTPUT.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".png":
            retint_png(path)
        elif path.suffix == ".css":
            path.write_text(retint_css(path.read_text(encoding="utf-8")), encoding="utf-8")
        elif path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            path.write_text(retint_text(path.read_text(encoding="utf-8")), encoding="utf-8")

    gtk3 = OUTPUT / "gtk-3.0/gtk.css"
    gtk3.write_text(apply_role_lightness(gtk3.read_text(encoding="utf-8")), encoding="utf-8")

    (OUTPUT / "index.theme").write_text(
        "[Desktop Entry]\n"
        "Type=X-GNOME-Metatheme\n"
        f"Name={THEME_NAME}\n"
        "Comment=Dark counterpart of Cinnamon-Delight for CaramOS\n"
        "Encoding=UTF-8\n\n"
        "[X-GNOME-Metatheme]\n"
        f"GtkTheme={THEME_NAME}\n"
        "MetacityTheme=Mint-Y\n"
        "IconTheme=Tela-circle-dark\n"
        "CursorTheme=Bibata-Modern-Classic\n"
        "ButtonLayout=menu:minimize,maximize,close\n",
        encoding="utf-8",
    )
    (OUTPUT / "README.md").write_text(
        f"# {THEME_NAME}\n\n"
        "Dark counterpart of **Cinnamon-Delight** used by CaramOS dark mode.\n\n"
        f"Generated by `packages/caramos-ota/tools/build-delight-dark-theme.py` from **Mint-Relaxed** by DrMcC0y\n"
        f"({UPSTREAM_URL}, commit `{UPSTREAM_COMMIT}`), the dark edition of the same design:\n\n"
        "- every grey is re-tinted to Cinnamon-Delight's mauve hue at the same lightness;\n"
        "- content, sidebar, toolbar band, buttons and borders get the same lightness steps as Delight;\n"
        "- accent and status colours are unchanged;\n"
        "- the CaramOS three-dock panel CSS is appended in its dark colours.\n\n"
        "License: GNU General Public License v3.0, as the upstream theme (see `README.Mint-Relaxed.md`).\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, help="existing Mint-Relaxed checkout (default: clone the pinned commit)")
    args = parser.parse_args()
    if args.source:
        build(args.source.resolve())
    else:
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp) / "Mint-Relaxed"
            subprocess.run(["git", "clone", "--quiet", UPSTREAM_URL, str(checkout)], check=True)
            subprocess.run(["git", "-C", str(checkout), "checkout", "--quiet", UPSTREAM_COMMIT], check=True)
            build(checkout)
    print(f"[OK] wrote {OUTPUT.relative_to(PKG_DIR)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
