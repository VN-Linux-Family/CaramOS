"""Constants for the CaramOS OTA updater."""

from pathlib import Path

TOOL_VERSION = "1.0.2-0caramos1"
TOOL_NAME = "caramos-ota"

STATE_DIR = Path("/var/lib/caramos-ota")
STATE_FILE = STATE_DIR / "state.json"
LOCK_FILE = STATE_DIR / "lock"
LOG_DIR = Path("/var/log/caramos-ota")
RELEASE_FILE = Path("/etc/caramos-release")
KEYRING_FILE = Path("/usr/share/keyrings/caramos-archive-keyring.gpg")
PPA_PATTERN = "ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_ROOT = 2
EXIT_NOT_CARAMOS = 3
EXIT_REPO = 4
EXIT_APT = 5
EXIT_STATE = 6
EXIT_LOCK = 7
EXIT_CANCEL = 8
