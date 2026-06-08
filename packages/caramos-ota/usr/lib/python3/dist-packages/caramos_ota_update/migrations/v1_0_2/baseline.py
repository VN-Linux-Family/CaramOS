"""Migration for PR #40: rebuild mintwelcome translations for CaramOS branding."""

from __future__ import annotations

import os
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.1"
TO_VERSION = "1.0.2"
DESCRIPTION = "PR #40: rebuild mintwelcome .mo translation files for CaramOS branding"

_SCRIPT = Path(__file__).with_name("apply_pr_40.sh")


def run(context: MigrationContext) -> None:
    """Run the original bash-style PR #40 migration logic."""

    env = os.environ.copy()
    env["CARAMOS_OTA_DRY_RUN"] = "1" if context.dry_run else "0"
    context.run_command(["bash", str(_SCRIPT)], env=env)
