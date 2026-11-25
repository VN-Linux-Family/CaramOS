"""The VNLF apps website (apps.vietnamlinuxfamily.net) installs apps on CaramOS with one click.

The site's "Cài trên CaramOS" buttons open caramos-app://install/<Flathub app id>, which the App Center takes: it shows
the app and installs it from Flathub with its own progress and password question (setting Flatpak up first when it is
missing). Firefox asked "Allow apps.vietnamlinuxfamily.net to open the caramos-app link with App Center?" first; it now
opens those links without asking, and only when they come from the apps website
(caramos_ota_update.firefox_policies keeps the rest of the policies file as it is). An App Center older than the one
that knows these links leaves them unopened, as before.
"""

from __future__ import annotations

from caramos_ota_update import firefox_policies
from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Firefox opens the apps website's install links in the App Center without asking"

ENTRIES = ({"protocol": "caramos-app", "allowed_origins": ["https://apps.vietnamlinuxfamily.net"]},)


def run(context: MigrationContext, desktop: str | None = None) -> None:
    if firefox_policies.allow_auto_launch(context, ENTRIES):
        context.log("Firefox opens caramos-app links from apps.vietnamlinuxfamily.net without asking")
    else:
        context.log("the apps website's install links still ask in Firefox (its policies file could not be read)")
