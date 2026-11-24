"""The names under the Xfce desktop's icons read on light wallpapers too (ticket H-1187): a dark shadow on every side,
in the Xfce edition's theme CSS (panel-islands.css, imported by the theme).

xfdesktop 4.18 styles its icons with its own CSS (fallback_CSS in xfdesktop-application.c, at application priority)
only while the GTK theme's CSS never names XfdesktopIconView. Once the theme names it, xfdesktop leaves everything to
the theme: without the rest of its rules the names would sit on the theme's white list background and the selected
icon would be tinted with the theme's text colour. So the theme repeats all of xfdesktop's rules, and only the
names' shadow is stronger."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIGHT = ROOT / "usr/share/caramos-ota/xfce/panel-islands.css"

# xfdesktop 4.18.1's fallback_CSS: what it styles itself when the theme does not.
XFDESKTOP_RULES = {
    "XfdesktopIconView.view": ("background: transparent;", "color: @theme_selected_fg_color;", "border-radius: 3px;"),
    "XfdesktopIconView.view:active": ("background: alpha(@theme_selected_bg_color, 0.5);",
                                      "text-shadow: 0 1px 1px black;"),
    "XfdesktopIconView .rubberband": ("background: alpha(@theme_selected_bg_color, 0.2);",
                                      "border: 1px solid @theme_selected_bg_color;", "border-radius: 0;"),
    "XfdesktopIconView:active": ("color: @theme_selected_bg_color;",),
}


def rule(css: str, selector: str) -> str:
    match = re.search(rf"(?:^|\n){re.escape(selector)}(?:,\n[^{{]*)? \{{\n(.*?)\}}", css, re.S)
    if match is None:
        raise AssertionError(f"no rule for {selector}")
    return match.group(1)


class DesktopLabelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = LIGHT.read_text(encoding="utf-8")

    def test_all_of_xfdesktops_rules(self) -> None:
        for selector, lines in XFDESKTOP_RULES.items():
            body = rule(self.css, selector)
            for line in lines:
                self.assertIn(line, body, selector)

    def test_a_shadow_on_every_side(self) -> None:
        body = rule(self.css, "XfdesktopIconView.view.label")
        shadows = re.search(r"text-shadow: (.*?);", body, re.S).group(1)
        offsets = re.findall(r"(-?\d+)(?:px)? (-?\d+)(?:px)? \d+px", shadows)
        self.assertEqual({("0", "1"), ("1", "0"), ("-1", "0"), ("0", "-1"), ("0", "2")}, set(offsets))

    def test_a_selected_icon_keeps_its_highlight(self) -> None:
        body = rule(self.css, "XfdesktopIconView.view.label:active")
        self.assertIn("text-shadow: 0 1px 1px black;", body)
        self.assertIn("XfdesktopIconView.view.label:selected", self.css)
        self.assertNotIn("background-color: transparent", self.css.split("XfdesktopIconView.view.label {")[1][:400],
                         "the names keep the highlight's background when selected")


if __name__ == "__main__":
    unittest.main()
