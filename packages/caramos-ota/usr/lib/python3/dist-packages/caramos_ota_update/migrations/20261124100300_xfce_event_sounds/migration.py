"""Event sounds work on the Xfce edition, when someone turns them on (ticket H-1206): Settings Manager > Appearance >
Settings > Enable event sounds. They stay off by default, as before: computers in a school lab stay quiet.

The switch did nothing: GTK plays event sounds only through canberra-gtk-module, which nothing loaded on Xfce. The
CaramOS Control Center now loads it into applications while the switch is on (caramos_xfce_cc/backends/event_sounds.py),
as GNOME and Cinnamon do. This adds what it needs where it is missing: the module, libcanberra's sound server
backend and the freedesktop sound theme (well under 1 MB; Linux Mint's Xfce edition has them already).

CaramOS's default settings (/etc/xdg/caramos-xfce/.../xsettings.xml, the ISO's file) blanked Xfce's own defaults of the
two switches and the sound theme: they now say off, off and freedesktop again, so the Control Center reads the switches
as Appearance shows them. A user's own choice stays. It shows from the next login, when the Control Center starts again.
"""

from __future__ import annotations

from pathlib import Path

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Xfce: Appearance's Enable event sounds works (off by default)"

PACKAGES = ("libcanberra-gtk3-module", "libcanberra-pulse", "sound-theme-freedesktop")
XSETTINGS = Path("/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml")
# CaramOS 1.4.0-1.5.0's blanks, and Xfce's own defaults (xfce4-settings' xsettings.xml) put back.
LINES = (
    ('<property name="SoundThemeName" type="empty"/>',
     '<property name="SoundThemeName" type="string" value="freedesktop"/>'),
    ('<property name="EnableEventSounds" type="empty"/>',
     '<property name="EnableEventSounds" type="bool" value="false"/>'),
    ('<property name="EnableInputFeedbackSounds" type="empty"/>',
     '<property name="EnableInputFeedbackSounds" type="bool" value="false"/>'),
)


def defaults_updated(text: str) -> str:
    """CaramOS's xsettings defaults with the sound settings of Xfce; "" when there is nothing to change."""

    lines = text.splitlines(keepends=True)
    changed = False
    for index, line in enumerate(lines):
        for before, after in LINES:
            if line.strip() == before:
                lines[index] = line.replace(before, after)
                changed = True
    return "".join(lines) if changed else ""


def _installed(context: MigrationContext, package: str) -> bool:
    result = context.run_command(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", package], allow_fail=True)
    return result is not None and result.returncode == 0 and result.stdout.startswith("ii")


def run(context: MigrationContext) -> None:
    missing = [package for package in PACKAGES if not _installed(context, package)]
    if missing:
        try:
            context.apt_install(missing, recommends=False)
        except MigrationContextError as exc:
            context.log(f"could not install {', '.join(missing)} ({exc}); event sounds stay silent without them")
    else:
        context.log(f"{', '.join(PACKAGES)} installed")
    try:
        new = defaults_updated(XSETTINGS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        context.log(f"no {XSETTINGS}: not the CaramOS Xfce edition")
        return
    except (OSError, UnicodeDecodeError):
        new = ""
    if new:
        context.write_file_if_changed(XSETTINGS, new)
    else:
        context.log(f"{XSETTINGS}: the sound settings are Xfce's already; left alone")
