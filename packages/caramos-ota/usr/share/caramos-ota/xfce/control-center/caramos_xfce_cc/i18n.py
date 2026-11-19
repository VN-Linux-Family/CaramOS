"""Translations: the gettext domain of the Cinnamon Control Center, so both editions say the same thing.

po/caramos-control-center/vi.po holds the strings of both (see po/README.md).
"""

from __future__ import annotations

import gettext
import os

DOMAIN = "caramos-control-center"
LOCALE_DIR = os.environ.get("CARAMOS_CC_LOCALEDIR", "/usr/share/locale")

_translation = gettext.translation(DOMAIN, localedir=LOCALE_DIR, fallback=True)


def _(message: str) -> str:
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    return _translation.ngettext(singular, plural, count)
