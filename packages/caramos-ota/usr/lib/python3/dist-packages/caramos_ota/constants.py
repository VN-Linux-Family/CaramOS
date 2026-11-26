"""Constants for the CaramOS OTA updater."""

from pathlib import Path

TOOL_VERSION = "1.5.2-0caramos2"
TOOL_NAME = "caramos-ota"

STATE_DIR = Path("/var/lib/caramos-ota")
STATE_FILE = STATE_DIR / "state.json"
MIGRATION_LEDGER_FILE = STATE_DIR / "migrations.json"
LOCK_FILE = STATE_DIR / "lock"
LOG_DIR = Path("/var/log/caramos-ota")
RELEASE_FILE = Path("/etc/caramos-release")
KEYRING_FILE = Path("/usr/share/keyrings/caramos-archive-keyring.gpg")
PPA_PATTERN = "ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os"

# dpkg asks nothing when caramos-ota, its migrations or its helpers install packages: they run without a terminal (the
# Update Center, the daily check, Driver Check, Phòng máy). There dpkg read end-of-file at a question about a
# configuration file, caramos-ota stayed unconfigured, and the computer could not update any more (ticket H-1207).
# A configuration file someone changed stays as it is, with the package's version next to it (.dpkg-dist); any
# other takes the package's version. Automatic updates give dpkg the same options through APT_CONFIG
# (/usr/share/caramos-ota/auto-update/apt.conf; a test keeps the two the same).
DPKG_NONINTERACTIVE_OPTIONS = ("--force-confdef", "--force-confold")
# apt waits up to this long for dpkg's lock instead of failing at once: Ubuntu's apt-daily-upgrade or another program
# installing at the same moment (often right after the computer starts, when automatic updates also run) made a
# migration's install fail with exit 100. Automatic updates have the same in their apt.conf.
DPKG_LOCK_TIMEOUT_SECONDS = 120
APT_NONINTERACTIVE_OPTIONS = tuple(
    part for option in DPKG_NONINTERACTIVE_OPTIONS for part in ("-o", f"Dpkg::Options::={option}")
) + ("-o", f"DPkg::Lock::Timeout={DPKG_LOCK_TIMEOUT_SECONDS}")
# No debconf questions either, and ucf keeps a configuration file someone changed, as dpkg does.
NONINTERACTIVE_ENV = {"DEBIAN_FRONTEND": "noninteractive", "UCF_FORCE_CONFFOLD": "1"}

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_ROOT = 2
EXIT_NOT_CARAMOS = 3
EXIT_REPO = 4
EXIT_APT = 5
EXIT_STATE = 6
EXIT_LOCK = 7
EXIT_CANCEL = 8
