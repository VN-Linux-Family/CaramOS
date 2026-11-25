"""Online Accounts (Tài khoản trực tuyến): signing in to Google or Microsoft no longer stops halfway in Firefox.

GNOME Online Accounts signs in through the default browser. The sign-in page hands its answer back through a link of
GNOME's own (com.googleusercontent.apps.…:/oauth2redirect for Google, goa-oauth2: for Microsoft), which the GNOME
OAuth2 Handler opens. Firefox first asked "Open the … link with GNOME OAuth2 Handler?", in English: whoever pressed
Cancel or missed it saw the Online Accounts window close without a word, and no account was added (a user's report,
2026-11-25; reproduced on a 1.5.1 VM).

Firefox's AutoLaunchProtocolsFromOrigins policy now opens exactly those links without asking, and only when they come
from the providers' sign-in pages (caramos_ota_update.firefox_policies keeps the rest of the policies file as it is).
"""

from __future__ import annotations

from caramos_ota_update import firefox_policies
from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Firefox hands the Online Accounts sign-in (Google, Microsoft) back without asking"

# gnome-online-accounts 3.50 (/usr/share/applications/org.gnome.OnlineAccounts.OAuth2.desktop).
GOOGLE_SCHEME = "com.googleusercontent.apps.44438659992-7kgjeitenc16ssihbtdjbgguch7ju55s"
ENTRIES = (
    {"protocol": GOOGLE_SCHEME, "allowed_origins": ["https://accounts.google.com"]},
    {"protocol": "goa-oauth2", "allowed_origins": ["https://login.microsoftonline.com", "https://login.live.com"]},
)


def run(context: MigrationContext, desktop: str | None = None) -> None:
    if firefox_policies.allow_auto_launch(context, ENTRIES):
        context.log("Firefox opens the Online Accounts sign-in links without asking (from the next start of Firefox)")
    else:
        context.log("Online Accounts sign-in still asks in Firefox (its policies file could not be read)")
