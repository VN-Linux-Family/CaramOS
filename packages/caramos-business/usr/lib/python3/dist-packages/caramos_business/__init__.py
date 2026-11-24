"""CaramOS Doanh nghiệp: a company's admin machine manages its employees' machines on the LAN: the wallpaper and
the folders on the company's server (0.1); from 0.2 departments, browsers, printers, Wi-Fi, apps, the power
schedule, USB storage, the screen lock and the firewall, with instant actions, an inventory and remote help that the
employee accepts; from 0.3 safe pairing, enrolment files, shared machines, snapshots, tickets, reports and assets.
The contract between the parts is PROTOCOL.md in the source package."""

from __future__ import annotations

from pathlib import Path

VERSION = "0.3.1"

ETC = Path("/etc/caramos-business")
ROLE_FILE = ETC / "role"
ADMIN_KEY = ETC / "admin-key.pem"
ADMIN_BOX_KEY = ETC / "admin-box.key"
AGENT_CONFIG = ETC / "agent.json"
AGENT_BOX_KEY = ETC / "agent-box.key"
ENROLL_ON_BOOT = ETC / "enroll-on-boot.json"
STATE = Path("/var/lib/caramos-business")
ADMIN_STATE = STATE / "admin"
AGENT_STATE = STATE / "agent"
OS_MACHINE_ID = Path("/etc/machine-id")
RUN = Path("/run/caramos-business")
PAIRING = RUN / "pairing.json"
REMOTE_HELP_PSK = RUN / "remote-help.psk"

ADMIN = "admin"
EMPLOYEE = "employee"
ROLES = (ADMIN, EMPLOYEE)

SERVER_UNIT = "caramos-business-server.service"
AGENT_UNIT = "caramos-business-agent.service"
REMOTE_HELP_UNIT = "caramos-business-remote-help"
ENROLL_UNIT = "caramos-business-enroll.service"
HOSTNAME_UNIT = "caramos-business-hostname.service"
HELPER = "/usr/lib/caramos-business/caramos-business-helper"
AGENT = "/usr/lib/caramos-business/caramos-business-agent"
DATA = Path("/usr/share/caramos-business")
GUIDE = Path("/usr/share/doc/caramos-business/HUONG-DAN.md")
TEMPLATES = DATA / "templates"
APP_CENTER_CATALOG = Path("/usr/share/caramos-app-center/catalog.json")

# Remote help (PROTOCOL.md parts 2 and 3): the viewer listens here on the admin machine, behind stunnel's TLS port
# (a pre-shared key per session from 0.3).
VIEWER_PORT = 5500
REMOTE_HELP_PORT = 5501


def role(path: Path | None = None) -> str | None:
    """This machine's role, or None before one is chosen."""

    try:
        value = (path or ROLE_FILE).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return value if value in ROLES else None
