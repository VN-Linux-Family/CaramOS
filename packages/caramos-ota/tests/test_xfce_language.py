"""CaramOS Xfce speaks English by default (owner, 2026-11-19): the school lab edition follows Windows in the Tin học
textbooks, and Xfce's own Vietnamese translations are partial and often wrong. The Cinnamon edition stays Vietnamese.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HOOK = REPO / "config/hooks/live/0100-caramos-setup.hook.chroot"
BOOT_CONFIG = REPO / "scripts/boot_config.sh"


def locale_files(hook: str) -> tuple[str, str]:
    """The /etc/default/locale the hook writes for the Xfce edition and for Cinnamon."""

    block = hook.split("# --- Locale/timezone/identity ---", 1)[1].split("ln -snf /usr/share/zoneinfo", 1)[0]
    files = re.findall(r"cat > /etc/default/locale <<'LOCALE'\n(.*?)\nLOCALE", block, re.S)
    if 'if [ "${MINT_EDITION:-cinnamon}" = xfce ]; then' not in block or len(files) != 2:
        raise AssertionError("the hook no longer writes one locale file per edition")
    return files[0], files[1]


@unittest.skipUnless(HOOK.is_file(), "the source package has no config/")
class XfceLanguageTests(unittest.TestCase):
    def test_xfce_installs_in_english_with_vietnamese_paper(self) -> None:
        xfce, cinnamon = locale_files(HOOK.read_text(encoding="utf-8"))
        self.assertEqual(["LANG=en_US.UTF-8", "LC_PAPER=vi_VN.UTF-8", "LC_MEASUREMENT=vi_VN.UTF-8"], xfce.splitlines())
        # No LANGUAGE: the installer rewrites only LANG, so choosing Vietnamese there still gives Vietnamese.
        self.assertNotIn("LANGUAGE", xfce)
        self.assertEqual(["LANG=vi_VN.UTF-8", "LANGUAGE=vi_VN:vi"], cinnamon.splitlines())

    def test_the_live_session_and_the_installer_start_in_english(self) -> None:
        script = BOOT_CONFIG.read_text(encoding="utf-8")
        self.assertIn('local LIVE_LOCALE="vi_VN.UTF-8"', script)
        self.assertRegex(script, r'if \[ "\$\{MINT_EDITION:-cinnamon\}" = xfce \]; then\n\s+LIVE_LOCALE="en_US\.UTF-8"\n')
        self.assertEqual(2, script.count("boot=casper locale=${LIVE_LOCALE}"))


if __name__ == "__main__":
    unittest.main()
