"""Desktop notifier constants."""

from caramos_ota.constants import EXIT_LOCK, STATE_FILE

OTA_COMMAND = "/usr/bin/caramos-ota"
PKEXEC_COMMAND = "pkexec"
UPGRADE_TIMEOUT_SECONDS = 600

# How an update run ended (app.run_upgrade_stream).
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"   # pkexec: the password window was closed, or the account may not update the system
BUSY = "busy"             # another caramos-ota run holds the lock: another Update Center window, the daily check
PKEXEC_REFUSED = (126, 127)
OTA_BUSY = EXIT_LOCK
