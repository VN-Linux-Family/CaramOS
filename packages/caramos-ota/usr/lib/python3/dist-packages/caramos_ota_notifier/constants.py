"""Desktop notifier constants."""

from caramos_ota.constants import EXIT_LOCK, STATE_FILE

OTA_COMMAND = "/usr/bin/caramos-ota"
PKEXEC_COMMAND = "pkexec"
UPGRADE_TIMEOUT_SECONDS = 600
# The Update Center, opened by hand, runs the daily check first (pkexec, no password: polkit action
# net.vietnamlinuxfamily.caramos-ota.check). Up to 1.5.0 it only read the updater already installed, so a computer whose
# daily check kept failing was told it was up to date (CaramOS 1.3.3 computers, 2026-11).
CHECK_HELPER = "/usr/share/caramos-ota/check/caramos-ota-check-helper"
CHECK_TIMEOUT_SECONDS = 300

# How an update run ended (app.run_upgrade_stream).
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"   # pkexec: the password window was closed, or the account may not update the system
BUSY = "busy"             # another caramos-ota run holds the lock: another Update Center window, the daily check
CHECKED = "checked"       # a check for new versions worked (app.run_check)
OFFLINE = "offline"       # a check could not reach the CaramOS update server
PKEXEC_REFUSED = (126, 127)
OTA_BUSY = EXIT_LOCK
