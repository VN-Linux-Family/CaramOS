"""Stop forcing Vietnamese through the system locale file (#65).

CaramOS ISOs up to 1.0.19 wrote LC_ALL=vi_VN.UTF-8 into /etc/default/locale (a symlink to
/etc/locale.conf on Mint 22). PAM loads that file into every session, and LC_ALL overrides LANG and
every LC_* variable, so choosing English in Settings > Languages left many applications, dates and
the folder-rename prompt in Vietnamese. locale.conf(5) does not allow LC_ALL there at all.

The installer only rewrites LANG, so a machine installed in English also kept LANGUAGE=vi_VN:vi,
which makes gettext pick Vietnamese translations first. And when the installer wrote LANG="vi_VN"
without a codeset, Settings > Languages shows "vi_VN" instead of "Vietnamese, Vietnam".

Only the values CaramOS wrote are changed; anything else in the file is left as it is. The new
values take effect at the next login.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Remove the forced Vietnamese LC_ALL from the system locale so the chosen language applies"

LOCALE_FILES = (Path("/etc/locale.conf"), Path("/etc/default/locale"))

CARAMOS_LC_ALL = {"vi_VN.UTF-8", "vi_VN.utf8", "vi_VN"}
CARAMOS_LANGUAGE = "vi_VN:vi"

_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Z_]+)=(.*?)\s*$")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _language_for(lang: str) -> str | None:
    """Return the LANGUAGE value Mint's Languages tool would write for LANG, e.g. en_US:en."""

    info = lang.split(".")[0].split("@")[0]
    if not info or info in {"C", "POSIX"}:
        return None
    return f"{info}:{info.split('_')[0]}"


def fixed_content(content: str) -> str:
    """Return the locale file content without the values CaramOS forced."""

    values: dict[str, str] = {}
    for line in content.splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            values[match.group(1)] = _unquote(match.group(2))
    lang = values.get("LANG", "")
    if lang == "vi_VN":
        lang = "vi_VN.UTF-8"

    output: list[str] = []
    for line in content.splitlines(keepends=True):
        match = _ASSIGNMENT.match(line.rstrip("\n"))
        if not match:
            output.append(line)
            continue
        key, value = match.group(1), _unquote(match.group(2))
        if key == "LC_ALL" and value in CARAMOS_LC_ALL:
            continue
        if key == "LANG" and value == "vi_VN":
            output.append("LANG=vi_VN.UTF-8\n")
            continue
        if key == "LANGUAGE" and value == CARAMOS_LANGUAGE and not lang.startswith("vi_"):
            language = _language_for(lang)
            if language is not None:
                output.append(f"LANGUAGE={language}\n")
            continue
        output.append(line)
    return "".join(output)


def _locale_files() -> list[Path]:
    """Real files behind LOCALE_FILES, once each (/etc/default/locale is usually a symlink)."""

    seen: set[Path] = set()
    files: list[Path] = []
    for path in LOCALE_FILES:
        if not path.is_file():
            continue
        real = path.resolve()
        if real in seen:
            continue
        seen.add(real)
        files.append(real)
    return files


def _atomic_write(path: Path, content: str) -> None:
    mode = path.stat().st_mode & 0o7777
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(staging, mode)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def run(context: MigrationContext) -> None:
    files = _locale_files()
    if not files:
        context.log("no system locale file found; nothing to change")
        return
    for path in files:
        current = path.read_text(encoding="utf-8")
        updated = fixed_content(current)
        if updated == current:
            context.log(f"{path}: no forced Vietnamese locale values")
            continue
        removed = sorted(set(current.splitlines()) - set(updated.splitlines()))
        context.log(f"{path}: replace {', '.join(removed)} (applies at next login)")
        if not context.dry_run:
            _atomic_write(path, updated)
