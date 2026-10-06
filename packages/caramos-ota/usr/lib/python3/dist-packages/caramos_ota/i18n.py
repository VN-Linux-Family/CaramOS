"""Translations for CaramOS OTA user interfaces.

Source strings are English; Vietnamese comes from po/caramos-ota/vi.po, compiled at package build time
to /usr/share/locale/vi/LC_MESSAGES/caramos-ota.mo. The language follows the session the program runs
in (LANGUAGE, LC_ALL, LC_MESSAGES, LANG), so the desktop language chosen in Settings > Languages
applies after logging in again.

Update metadata is written by a root service that has no user language, so it carries both languages
(`title`/`title_en`, `summary`/`summary_en`); `localized()` picks the one for this session.
"""

from __future__ import annotations

import gettext
import os
from collections.abc import Mapping

DOMAIN = "caramos-ota"
LOCALE_DIR = os.environ.get("CARAMOS_OTA_LOCALEDIR", "/usr/share/locale")

_translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, fallback=True)


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    return _translation.ngettext(singular, plural, count)


def ui_language(environ: Mapping[str, str] | None = None) -> str:
    """Language code gettext uses for this session, e.g. "vi" or "en"."""

    env = os.environ if environ is None else environ
    for key in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(key, "").strip()
        if not value:
            continue
        first = value.split(":")[0]
        code = first.split(".")[0].split("@")[0].split("_")[0]
        if code and code not in {"C", "POSIX"}:
            return code
        if key != "LANGUAGE":
            break
    return "en"


def prefers_vietnamese(environ: Mapping[str, str] | None = None) -> bool:
    return ui_language(environ) == "vi"


def localized(item: Mapping[str, object], key: str, environ: Mapping[str, str] | None = None) -> object:
    """Return item[key] in Vietnamese sessions and item[key + "_en"] (when set) otherwise."""

    if not prefers_vietnamese(environ):
        english = item.get(f"{key}_en")
        if isinstance(english, str) and english.strip():
            return english
    return item.get(key)
