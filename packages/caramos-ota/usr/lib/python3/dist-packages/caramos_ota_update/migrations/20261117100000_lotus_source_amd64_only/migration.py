"""Ask the Lotus input method's package source for 64-bit packages only.

CaramOS adds the Lotus repository (fcitx5-lotus.pages.dev) without an architecture. Linux Mint turns 32-bit
packages (i386) on, for Steam and Wine, so every `apt update` also asks Lotus for 32-bit package lists, which it
does not publish, and prints

    N: Skipping acquire of configured file 'main/binary-i386/Packages' as repository '…fcitx5-lotus…'
       doesn't support architecture 'i386'

It is only a notice, but it reads like an error. The Lotus source lines get arch=amd64, as the ISO writes them
now (config/hooks/live/0150-fcitx5-lotus.hook.chroot).

Only sources that point at fcitx5-lotus.pages.dev and name no architecture change. A line or a deb822 stanza
that already names its architectures is left as it is, and so is everything else in the file.
"""

from __future__ import annotations

import re
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Ask the Lotus package source for 64-bit packages only"

SOURCES_DIR = Path("/etc/apt/sources.list.d")
HOST = "fcitx5-lotus.pages.dev"
ARCH = "amd64"

# "deb [options] uri suite components…" or "deb uri …", indented or not.
ONE_LINE = re.compile(r"^(?P<lead>\s*deb(?:-src)?\s+)(?:\[(?P<options>[^\]]*)\]\s*)?(?P<rest>\S.*)$")


def fix_one_line(text: str) -> str:
    """A .list file with arch=amd64 on each Lotus line that names no architecture."""

    lines = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        match = ONE_LINE.match(body)
        if match and HOST in match.group("rest"):
            options = match.group("options")
            if options is None:
                body = f"{match.group('lead')}[arch={ARCH}] {match.group('rest')}"
            elif not re.search(r"(^|\s)arch(\+|-)?=", options):
                inside = options.strip()
                body = f"{match.group('lead')}[arch={ARCH}{' ' + inside if inside else ''}] {match.group('rest')}"
        lines.append(body + ending)
    return "".join(lines)


def fix_deb822(text: str) -> str:
    """A .sources file with "Architectures: amd64" in each Lotus stanza that names none."""

    stanzas = re.split(r"(\n[ \t]*\n)", text)
    for index in range(0, len(stanzas), 2):
        stanza = stanzas[index]
        fields = [line.split(":", 1)[0].strip().lower() for line in stanza.splitlines()
                  if line and not line[0].isspace() and not line.startswith("#") and ":" in line]
        uris = [line for line in stanza.splitlines() if line.lower().startswith("uris:")]
        if any(HOST in line for line in uris) and "architectures" not in fields:
            ending = "\n" if stanza.endswith("\n") else ""
            stanzas[index] = stanza.rstrip("\n") + f"\nArchitectures: {ARCH}" + ending
    return "".join(stanzas)


def run(context: MigrationContext) -> None:
    if not SOURCES_DIR.is_dir():
        context.log(f"{SOURCES_DIR} does not exist; nothing to change")
        return
    changed = 0
    for path in sorted(SOURCES_DIR.iterdir()):
        if path.suffix not in (".list", ".sources") or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            context.log(f"skip {path}: {exc}")
            continue
        if HOST not in text:
            continue
        fixed = fix_one_line(text) if path.suffix == ".list" else fix_deb822(text)
        if fixed == text:
            context.log(f"{path} already names the architecture of the Lotus source")
            continue
        context.write_file_if_changed(path, fixed)
        changed += 1
    if not changed:
        context.log("no Lotus source without an architecture")
