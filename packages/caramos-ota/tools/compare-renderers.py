#!/usr/bin/env python3
"""Draw CaramOS's GTK 4 programs with OpenGL and with the renderer they choose themselves (caramos_ota/gtk_renderer.py,
caramos_app_center/renderer.py), on a test VM, and compare.

    VM_DOMAIN=caramxfce ./tools/compare-renderers.py [OUT_DIR]

For each program: start it in the VM's desktop, wait, read which renderer GTK used (GSK_DEBUG=renderer) and its memory
(PSS), take a screenshot, stop it; then the share of pixels that differ between the two screenshots (the taskbar,
whose clock moves, left out), and a picture of both side by side with the differences in red. Needs a VM made with
tools/vm-dev.sh with the working tree synced (and the App Center's changed files copied in), and Pillow on this host.
Exits 1 when a program's two pictures differ more than DIFF_LIMIT: a renderer that draws something else is a bug.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops

TOOLS = Path(__file__).resolve().parent
VM = [str(TOOLS / "vm-dev.sh")]
GUEST = TOOLS / "vm-guest" / "compare-renderers.sh"
PROGRAMS = (
    ("App Center", "caramos-app-center"),
    ("Driver Check", "caramos-driver-check"),
    ("Feedback & Help", "caramos-help"),
    ("Computer Lab", "caramos-lab"),
)
WAIT_S = 12
PANEL_TOP = 748          # the taskbar: its clock changes between the two pictures
PIXEL_THRESHOLD = 40     # a pixel differs when one channel moves more than this (text edges move by a few levels)
DIFF_LIMIT = 0.5         # percent of the screen


def vm(*args: str, check: bool = False, stdin: str | None = None) -> str:
    result = subprocess.run([*VM, *args], capture_output=True, text=True, check=check, input=stdin)
    return result.stdout


def run(command: str, renderer: str, out: Path) -> tuple[str, str, Path]:
    # The VM side is a script file (tools/vm-guest/compare-renderers.sh), never commands in the ssh command line.
    vm("run", str(GUEST), "stop", command, renderer)
    time.sleep(1)
    vm("run", "--bg", str(GUEST), "start", command, renderer)
    time.sleep(WAIT_S)
    shot = out / f"{command}-{renderer}.png"
    vm("shot", str(shot))
    lines = [line.strip() for line in vm("run", str(GUEST), "probe", command, renderer).splitlines() if line.strip()]
    memory = next((line for line in lines if line.endswith("MB")), "not running")
    used = next((line.split()[-1].strip("'") for line in lines if line.startswith("Using renderer")), "?")
    time.sleep(2)
    return memory, used, shot


def compare(first: Path, second: Path, picture: Path) -> float:
    a = Image.open(first).convert("RGB")
    b = Image.open(second).convert("RGB")
    box = (0, 0, a.width, min(PANEL_TOP, a.height))
    a, b = a.crop(box), b.crop(box)
    difference = ImageChops.difference(a, b).convert("L").point(lambda level: 255 if level > PIXEL_THRESHOLD else 0)
    changed = sum(1 for level in difference.getdata() if level)
    marked = b.copy()
    marked.paste((255, 0, 0), mask=difference)
    sheet = Image.new("RGB", (a.width * 2 + 20, a.height), "white")
    sheet.paste(a, (0, 0))
    sheet.paste(marked, (a.width + 20, 0))
    sheet.save(picture)
    return 100 * changed / (a.width * a.height)


def main(argv: list[str]) -> int:
    out = Path(argv[1] if len(argv) > 1 else "dist-testkit/renderers")
    out.mkdir(parents=True, exist_ok=True)
    failed = False
    print(f"VM {os.environ.get('VM_DOMAIN', '(vm.local.env)')}; pictures in {out}")
    for name, command in PROGRAMS:
        opengl = run(command, "ngl", out)
        chosen = run(command, "auto", out)
        if "not running" in (opengl[0], chosen[0]):
            print(f"{name}: did not start ({opengl[0]}, {chosen[0]})")
            failed = True
            continue
        changed = compare(opengl[2], chosen[2], out / f"{command}-compare.png")
        verdict = "same picture" if changed <= DIFF_LIMIT else "DIFFERENT"
        failed |= changed > DIFF_LIMIT
        print(f"{name}: OpenGL {opengl[0]} ({opengl[1]}); its own choice {chosen[0]} ({chosen[1]}); "
              f"{changed:.2f}% of the screen differs: {verdict}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
