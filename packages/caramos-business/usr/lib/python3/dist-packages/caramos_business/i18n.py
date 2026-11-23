"""Translations: the gettext domain caramos-business (po/vi.po in the source package)."""

from __future__ import annotations

import gettext
import os

DOMAIN = "caramos-business"
LOCALE_DIR = os.environ.get("CARAMOS_BUSINESS_LOCALEDIR", "/usr/share/locale")

_translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, fallback=True)


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    return _translation.ngettext(singular, plural, count)
