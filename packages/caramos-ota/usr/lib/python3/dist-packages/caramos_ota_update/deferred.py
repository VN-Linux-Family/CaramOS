"""What a migration leaves for later: the part that must not happen while someone works at the computer.

An automatic update (caramos_ota.auto_update) runs while people may be at work on an open desktop. A migration with
"unattended": "anytime" changes what it can at once: system files, the system's default settings, and the settings
of the accounts that are not logged in, which show from their next login. Two things wait:

At the user's next login (wait_for_login, queue_for_login)
    What a logged-in user would see change now: Cinnamon applies a gsettings change at once (a new applet on the
    panel, the Trash on the desktop), and xfce4-panel rebuilds itself when its plugin list changes (its embedded
    Control Center loses the clock). In an automatic update (context.unattended), such a migration calls
    wait_for_login() for each user with a session open: the step goes to QUEUE_DIR/<uid>.json (root's, readable by
    everyone). An entry names the migration and one of the names in that migration's LOGIN_ACTIONS, never a
    command. At the user's next login, before the desktop starts, /etc/X11/Xsession.d/96caramos-login-actions runs
    LOGIN_COMMAND as that user (main() below): each waiting action runs once, with a Session (the session's D-Bus,
    gsettings and xfconf-query as the user), and DONE_FILE (~/.local/state/caramos/login-actions.json) keeps what
    ran. An action reads the user's settings again at that time, so what the user changed in between counts.
    Updates from the Update Center (context.unattended False) change the open desktop at once, as before, and
    accounts that are not logged in change at once as well.

After an automatic login (autologin_keyring)
    The same command first gives a user LightDM logs in automatically a keyring that opens by itself, so that apps
    keep their sign-in; logins with a password are left alone.

At the next start (dconf_update_at_next_start)
    `dconf update` rebuilds the system's dconf database (/etc/dconf/db/local), which a running Cinnamon 6.6 does not
    survive. With someone logged in, a migration that changed /etc/dconf/db/local.d asks for it here: DCONF_FLAG,
    and caramos-ota-dconf-update.service runs `dconf update` at the next start, before anyone can log in. Until
    then only accounts made later miss the change: each existing account gets it through gsettings.
"""

from __future__ import annotations

import importlib
import json
import os
import pwd
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

from . import autologin_keyring
from .desktop import CINNAMON, XFCE, current_desktop
from .registry import TIMESTAMP_ID_RE

STATE_DIR = Path("/var/lib/caramos-ota")
QUEUE_DIR = STATE_DIR / "login-actions"
DCONF_FLAG = STATE_DIR / "dconf-update-pending"
RUNTIME_ROOT = Path("/run/user")
LOGIN_COMMAND = "/usr/share/caramos-ota/login/caramos-login-actions"
MIGRATIONS = "caramos_ota_update.migrations"
ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SCHEMA = 1
COMMAND_TIMEOUT = 15
# A step that fails at three logins in a row is given up: it would only slow down every login.
MAX_TRIES = 3
# An account nobody logged in to for a year: its old steps are dropped.
MAX_AGE = timedelta(days=365)


def queue_file(uid: int, queue_dir: Path | None = None) -> Path:
    return (queue_dir or QUEUE_DIR) / f"{uid}.json"


def logged_in(uid: int, runtime_root: Path | None = None) -> bool:
    """The user has a session open: their session bus (also an SSH login, which only waits too)."""

    return ((runtime_root or RUNTIME_ROOT) / str(uid) / "bus").exists()


def _now() -> datetime:
    return datetime.now().astimezone()


def _parse_time(value: object) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.astimezone()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _entries(data: Mapping[str, Any]) -> list[dict[str, str]]:
    found = []
    for entry in data.get("actions") or []:
        if (isinstance(entry, dict) and isinstance(entry.get("migration"), str)
                and isinstance(entry.get("action"), str)):
            found.append({"migration": entry["migration"], "action": entry["action"],
                          "queued_at": str(entry.get("queued_at") or "")})
    return found


def _fresh(entry: Mapping[str, str], now: datetime) -> bool:
    queued = _parse_time(entry.get("queued_at"))
    return queued is None or now - queued <= MAX_AGE


def key(migration: str, action: str) -> str:
    return f"{migration}/{action}"


def _write_atomic(path: Path, data: Mapping[str, Any], mode: int = 0o644) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), mode)
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


# The root side: migrations ---------------------------------------------------------------------------------------


def queue_for_login(context, migration: str, action: str, username: str, uid: int, *,
                    queue_dir: Path | None = None) -> None:
    """The step `action` of `migration` (a name in its LOGIN_ACTIONS) runs at the user's next login."""

    path = queue_file(uid, queue_dir)
    context.log(f"{migration}: {action} for {username} waits for their next login ({path})")
    if context.dry_run:
        return
    now = _now()
    data = _read_json(path)
    entries = [entry for entry in _entries(data) if _fresh(entry, now)] if data.get("user") == username else []
    if all(key(entry["migration"], entry["action"]) != key(migration, action) for entry in entries):
        entries.append({"migration": migration, "action": action, "queued_at": now.isoformat(timespec="seconds")})
    _write_atomic(path, {"schema": SCHEMA, "user": username, "actions": entries})


def wait_for_login(context, migration: str, action: str, username: str, uid: int, *,
                   runtime_root: Path | None = None, queue_dir: Path | None = None) -> bool:
    """Whether this user's visible step waits for their next login: in an automatic update, for a user with a
    session open. It is queued then (logged only in a dry run), and the migration leaves it out now."""

    if not getattr(context, "unattended", False) or not logged_in(uid, runtime_root):
        return False
    queue_for_login(context, migration, action, username, uid, queue_dir=queue_dir)
    return True


def dconf_update_at_next_start(context, flag: Path | None = None) -> None:
    """`dconf update` waits for the next start, before anyone logs in (caramos-ota-dconf-update.service)."""

    flag = flag or DCONF_FLAG
    context.log(f"someone is logged in: dconf update waits for the next start ({flag}); Cinnamon would crash under it")
    if context.dry_run:
        return
    flag.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    flag.write_text("dconf update\n", encoding="utf-8")


# The user's side: the login ---------------------------------------------------------------------------------------


@dataclass
class Session:
    """The login a waiting step runs in: as the user, with the session's environment (D-Bus, XDG_CONFIG_DIRS)."""

    username: str
    uid: int
    home: Path
    desktop: str
    environ: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    messages: list[str] = field(default_factory=list)

    def log(self, message: str) -> None:
        self.messages.append(message)
        # Into ~/.xsession-errors, with the rest of the login's messages.
        print(f"caramos-login-actions: {message}", file=sys.stderr)

    def run(self, args: list[str], timeout: float = COMMAND_TIMEOUT) -> subprocess.CompletedProcess[str]:
        """A command as this user; a command that cannot start or takes too long fails (127, 124)."""

        try:
            return subprocess.run([str(part) for part in args], check=False, capture_output=True, text=True,
                                  env=self.environ, stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, 124, "", f"{args[0]} took longer than {timeout} s")
        except OSError as exc:
            return subprocess.CompletedProcess(args, 127, "", str(exc))

    def gsettings(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run(["gsettings", *args])


def session_desktop(environ: Mapping[str, str]) -> str:
    """The desktop this login starts, from what LightDM set; else the edition's."""

    names = f"{environ.get('XDG_CURRENT_DESKTOP', '')}:{environ.get('DESKTOP_SESSION', '')}".lower()
    if "cinnamon" in names:
        return CINNAMON
    if "xfce" in names:
        return XFCE
    return current_desktop()


def done_file(environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    env = os.environ if environ is None else environ
    state_home = env.get("XDG_STATE_HOME") or str((home or Path.home()) / ".local" / "state")
    return Path(state_home) / "caramos" / "login-actions.json"


def find_action(migration: str, action: str) -> Callable[[Session], Any] | None:
    """The function a migration names `action` in its LOGIN_ACTIONS; None when there is none (any more)."""

    if not TIMESTAMP_ID_RE.fullmatch(migration) or not ACTION_RE.fullmatch(action):
        return None
    try:
        module = importlib.import_module(f"{MIGRATIONS}.{migration}.migration")
    except Exception:   # noqa: BLE001 - a migration that cannot be loaded runs nothing
        return None
    actions = getattr(module, "LOGIN_ACTIONS", None)
    function = actions.get(action) if isinstance(actions, Mapping) else None
    return function if callable(function) else None


def pending(username: str, uid: int, *, queue_dir: Path | None = None, done: Mapping[str, Any] | None = None,
            now: datetime | None = None) -> list[dict[str, str]]:
    """The user's queued steps that have not run yet."""

    data = _read_json(queue_file(uid, queue_dir))
    if data.get("user") != username:
        return []   # another account had this uid: its steps are not this one's
    finished = (done or {}).get("done") or {}
    now = now or _now()
    return [entry for entry in _entries(data)
            if key(entry["migration"], entry["action"]) not in finished and _fresh(entry, now)]


def run_pending(session: Session, *, queue_dir: Path | None = None, state_path: Path | None = None) -> int:
    """Run the user's waiting steps (the login); the number that ran."""

    path = state_path or done_file(session.environ, session.home)
    state = _read_json(path)
    state.setdefault("done", {})
    state.setdefault("tries", {})
    if not isinstance(state["done"], dict):
        state["done"] = {}
    if not isinstance(state["tries"], dict):
        state["tries"] = {}
    ran = 0
    changed = False
    for entry in pending(session.username, session.uid, queue_dir=queue_dir, done=state):
        name = key(entry["migration"], entry["action"])
        function = find_action(entry["migration"], entry["action"])
        if function is None:
            session.log(f"{name}: not in this version of caramos-ota; skipped")
            state["done"][name] = f"{_now().isoformat(timespec='seconds')} skipped"
            changed = True
            continue
        try:
            function(session)
        except Exception as exc:   # noqa: BLE001 - one step must not stop the others, nor the login
            tries = int(state["tries"].get(name) or 0) + 1
            state["tries"][name] = tries
            session.log(f"{name} failed ({exc}); "
                        + ("given up" if tries >= MAX_TRIES else "tried again at the next login"))
            if tries >= MAX_TRIES:
                state["done"][name] = f"{_now().isoformat(timespec='seconds')} failed"
            changed = True
            continue
        state["done"][name] = _now().isoformat(timespec="seconds")
        state["tries"].pop(name, None)
        ran += 1
        changed = True
    if changed:
        try:
            _write_atomic(path, state, mode=0o600)
        except OSError as exc:
            session.log(f"could not write {path}: {exc}")
    return ran


def main(argv: list[str] | None = None, *, queue_dir: Path | None = None, keyring=None) -> int:
    """LOGIN_COMMAND, before the desktop starts: after LightDM's automatic login, a keyring that opens by itself
    (autologin_keyring); then this user's waiting steps. Never fails the login."""

    argv = sys.argv[1:] if argv is None else argv
    if argv:
        print("caramos-login-actions takes no arguments", file=sys.stderr)
        return 2
    uid = os.getuid()
    if uid == 0:
        return 0
    try:
        entry = pwd.getpwuid(uid)
    except KeyError:
        return 0
    session = Session(entry.pw_name, uid, Path(entry.pw_dir), session_desktop(os.environ))
    try:
        if autologin_keyring.autologin_session(os.environ, session.run):
            service = keyring(session.run) if keyring is not None else autologin_keyring.SecretService(session.run)
            autologin_keyring.ensure(service, session.log, autologin_keyring.label_for(os.environ),
                                     keyrings=session.home / autologin_keyring.KEYRINGS)
    except Exception as exc:   # noqa: BLE001 - the login goes on whatever happens here
        session.log(f"keyring: {exc}")
    if not queue_file(uid, queue_dir).exists():
        return 0
    try:
        run_pending(session, queue_dir=queue_dir)
    except Exception as exc:   # noqa: BLE001 - the login goes on whatever happens here
        session.log(f"stopped: {exc}")
    return 0
