"""caramos-business-helper: what the window does as root, through pkexec (polkit action
net.vietnamlinuxfamily.caramos-business.helper).

    role admin|employee         choose the role (admin: keys, state, server; the firewall opened if ufw is on)
    pairing open|close          admin: let employees pair for 10 minutes with a new random code, or stop
    options                     admin: {"approve_machines": bool} on stdin
    approve ID, reject ID       admin: a machine waiting for approval joins, or is turned away
    enroll-token create FILE    admin: {"department", "days", "max_uses", "hostname_prefix"} on stdin; writes an
                                enrolment file as the user who ran the window
    enroll-token revoke ID      admin: an enrolment file stops working
    licences                    admin: the register of bought licences on stdin (a list)
    ticket                      admin: {"id", "status"?, "assignee"?, "note"?} on stdin
    policy                      admin: the window's draft on stdin ({"settings", "departments", "members",
                                "machines", "pictures": {"new:1": "/path/picture.jpg"}, "wifi_passphrases":
                                {"ssid": "..."}}): the pictures are copied in, the passphrases kept (root only) and
                                sealed for each machine, then the policy is saved as the next serial and signed
    command                     admin: {"targets", "action", "args", "help_id"?} on stdin: signed and queued for /wait
                                (help_id is a ticket answered with remote help)
    forget-machine ID           admin: take a machine out of the company (with a signed removal notice)
    asset ID                    admin: an asset's details on stdin (a machine id, or asset-<uuid4>)
    asset-new                   admin: a new asset without a machine on stdin
    remote-help start|stop      admin: the TLS end of remote help (stunnel on port 5501 with a key for the session,
                                as a transient unit) and the firewall rule that keeps the LAN off the viewer
    backup FILE                 admin: the passphrase on stdin; FILE is written as the user who ran the window
    restore FILE                a machine without a role: the passphrase on stdin; it becomes the admin
    pair IP CODE                employee: pair with the admin at IP (SPAKE2), then start the agent
    pair-file PATH              employee: pair with an enrolment file, then start the agent
    prepare-image               employee: {"enroll_file": path or null} on stdin; prepares the disk to be copied
    enroll-hostname             root, from caramos-business-hostname.service: the copy's host name, before the login
                                screen
    enroll-on-boot              root, from caramos-business-enroll.service: enrol with enroll-on-boot.json
    leave                       employee: unpair and stop the agent

It prints one JSON object on stdout: {"ok": true, ...} or {"ok": false, "error": "..."}. Every change on the admin
goes into the audit log with the user from PKEXEC_UID.
"""

from __future__ import annotations

import contextlib
import json
import os
import pwd
import secrets
import shutil
import socket
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from . import (ADMIN, ADMIN_BOX_KEY, ADMIN_KEY, ADMIN_STATE, AGENT, AGENT_BOX_KEY, AGENT_CONFIG, AGENT_STATE,
               AGENT_UNIT, EMPLOYEE, ENROLL_ON_BOOT, ENROLL_UNIT, ETC, HOSTNAME_UNIT, OS_MACHINE_ID, PAIRING,
               REMOTE_HELP_PORT,
               REMOTE_HELP_PSK, REMOTE_HELP_UNIT, ROLE_FILE, RUN, SERVER_UNIT, VIEWER_PORT, admin, assets, backup, client,
               health, licences, pairing as pairing_module, protocol, role, summaries, text, tickets)
from .i18n import _, ngettext
from .store import locked, write_atomic, write_json

PUBLIC_AGENT_INFO = AGENT_STATE / "admin.json"  # who this machine is paired with, readable by the window
REMOTE_HELP_CONF = RUN / "remote-help.conf"
REMOTE_HELP_RULE = "caramos-business-remote-help"
MAX_POLICY_INPUT = 4 * 1024 * 1024
DBUS_MACHINE_ID = Path("/var/lib/dbus/machine-id")
SSH_DIR = Path("/etc/ssh")
HOSTS = Path("/etc/hosts")
PROC_MOUNTS = Path("/proc/mounts")


class HelperError(Exception):
    pass


def systemctl(*args: str) -> None:
    try:
        result = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        raise HelperError(f"systemctl {' '.join(args)}: no answer in 60 s") from exc
    if result.returncode != 0:
        raise HelperError(f"systemctl {' '.join(args)}: {result.stderr.strip()}")


def ufw_active() -> bool:
    if not shutil.which("ufw"):
        return False
    status = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=30, check=False)
    return "Status: active" in status.stdout


def ufw(*args: str) -> None:
    subprocess.run(["ufw", *args], capture_output=True, timeout=30, check=False)


def open_firewall(role_name: str = ADMIN) -> None:
    """ufw is installed but off on CaramOS; when someone turned it on, the admin's ports must pass, and on an employee
    machine discovery's answers (UDP 47021, PROTOCOL.md part 1 "Discovery")."""

    if ufw_active():
        rules = [f"{protocol.UDP_PORT}/udp", f"{protocol.HTTP_PORT}/tcp"] if role_name == ADMIN else \
            [f"{protocol.UDP_PORT}/udp"]
        for rule in rules:
            ufw("allow", rule)


def hostname() -> str:
    return socket.gethostname().split(".")[0]


def user() -> str:
    return admin.pkexec_user()


def set_role(value: str) -> dict[str, Any]:
    if value not in (ADMIN, EMPLOYEE):
        raise HelperError(_("Unknown role."))
    current = role()
    if current and current != value:
        raise HelperError(_("This machine is the admin machine already.") if current == ADMIN else
                          _("This machine is an employee machine already: leave the admin machine first."))
    if value == ADMIN:
        ensure_admin()
        open_firewall()
        write_atomic(ROLE_FILE, b"admin\n")
        systemctl("enable", SERVER_UNIT)
        systemctl("restart", SERVER_UNIT)
        audit("role", _("This machine became the admin machine."))
    else:
        open_firewall(EMPLOYEE)
        write_atomic(ROLE_FILE, b"employee\n")
    return {"role": value}


def need(value: str) -> None:
    if role() != value:
        raise HelperError(_("This machine is not the admin machine.") if value == ADMIN else
                          _("This machine is not an employee machine."))
    if value == ADMIN:  # an admin from 0.1 gets the box key and the folder's group here
        ensure_admin()


def ensure_admin() -> None:
    """The admin's state folder, keys and a signed policy, made where missing."""

    admin.prepare_state(ADMIN_STATE)
    admin.ensure_key(ADMIN_KEY, ADMIN_STATE)
    admin.ensure_box_key(ADMIN_BOX_KEY)
    # A first policy with nothing turned on: the machines check the admin's signature on it before they check in, so
    # without it a new admin's machines never report, and show as off, until a setting is saved.
    if not (ADMIN_STATE / admin.SIGNED).exists():
        with locked(ADMIN_STATE):
            if not (ADMIN_STATE / admin.SIGNED).exists():
                save(admin.empty_draft())


def audit(kind: str, summary: str, **details: Any) -> None:
    admin.audit(kind, summary, user(), ADMIN_STATE, **details)


def pairing(action: str) -> dict[str, Any]:
    need(ADMIN)
    if action == "open":
        RUN.mkdir(parents=True, exist_ok=True)
        window = admin.open_pairing(path=PAIRING)
        audit("pairing", _("Adding machines opened for 10 minutes."), pairing="open")
        return window
    if action == "close":
        admin.close_pairing(PAIRING)
        audit("pairing", _("Adding machines closed."), pairing="closed")
        return {}
    raise HelperError("open or close")


def options(stdin: str) -> dict[str, Any]:
    need(ADMIN)
    with locked(ADMIN_STATE):
        value = admin.write_options(read_object(stdin), ADMIN_STATE)
        audit("options", _("Each new machine now waits for approval.") if value["approve_machines"] else
              _("New machines join without approval."), approve_machines=value["approve_machines"])
    return value


def approve(machine_id: str) -> dict[str, Any]:
    need(ADMIN)
    machine_id_arg(machine_id)
    with locked(ADMIN_STATE):
        entry = admin.approve_machine(machine_id, ADMIN_STATE)
        if entry is None:
            raise HelperError(_("This machine is not waiting for approval."))
        name = admin.machine_name({machine_id: entry}, machine_id)
        department = entry.get("department")
        current = admin.read_policy(ADMIN_STATE)
        if current.get("serial"):
            draft = admin.draft_from_policy(current)
            if department and department in draft["departments"]:
                draft["members"][machine_id] = department
            save(draft)
        audit("approve", _("%s was approved and joined the company.") % name, machine_id=machine_id, name=name)
    return {}


def reject(machine_id: str) -> dict[str, Any]:
    need(ADMIN)
    machine_id_arg(machine_id)
    with locked(ADMIN_STATE):
        entry = admin.reject_machine(machine_id, ADMIN_STATE)
        if entry is None:
            raise HelperError(_("This machine is not waiting for approval."))
        name = admin.machine_name({machine_id: entry}, machine_id)
        audit("reject", _("%s was turned away.") % name, machine_id=machine_id, name=name)
    return {}


def admin_address() -> str:
    """This machine's LAN address, as employees reach it: the source address of the default route."""

    try:
        ip, _mac = client.route_toward("1.1.1.1")
    except OSError:
        ip = ""
    if not ip or ip.startswith("127."):
        raise HelperError(_("This machine has no network address: connect it to the company's network first."))
    return ip


def enroll_token(action: str, value: str, stdin: str) -> dict[str, Any]:
    need(ADMIN)
    if action == "revoke":
        if not protocol.TOKEN_ID.match(value):
            raise HelperError(_("Unknown enrolment file."))
        with locked(ADMIN_STATE):
            if not pairing_module.revoke_token(ADMIN_STATE, value):
                raise HelperError(_("Unknown enrolment file."))
            audit("enroll-token", _("An enrolment file was withdrawn."), token_id=value, token="revoked")
        return {}
    if action != "create":
        raise HelperError("create or revoke")
    path = file_arg(value)
    with locked(ADMIN_STATE):
        departments = admin.read_policy(ADMIN_STATE).get("departments") or {}
        chosen = pairing_module.validate_token_options(read_object(stdin), departments)
        key = admin.ensure_key(ADMIN_KEY, ADMIN_STATE)
        department_name = (departments.get(chosen["department"]) or {}).get("name", "") if chosen["department"] else ""
        box = protocol.b64(protocol.box_public(admin.ensure_box_key(ADMIN_BOX_KEY)))
        data = pairing_module.create_token(ADMIN_STATE, chosen, admin_url=client.admin_url(admin_address()),
                                           admin_name=hostname(), admin_key=protocol.b64(protocol.public_bytes(key)),
                                           admin_box_key=box, department_name=department_name, by=user())
        with as_invoker():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=1)
                    handle.write("\n")
            except OSError as exc:
                pairing_module.revoke_token(ADMIN_STATE, data["token_id"])
                raise HelperError(_("Could not write %(file)s: %(error)s") % {"file": path, "error": exc.strerror}) \
                    from exc
        audit("enroll-token", _("An enrolment file was made: %(uses)d machines, until %(until)s.")
              % {"uses": chosen["max_uses"], "until": text.vn_date(data["expires"][:10])}, token_id=data["token_id"],
              token="created", department=chosen["department"], max_uses=chosen["max_uses"],
              expires=data["expires"], file=path.name)
    return {"token_id": data["token_id"], "expires": data["expires"]}


def licences_command(stdin: str) -> dict[str, Any]:
    need(ADMIN)
    try:
        value = json.loads(stdin)
    except ValueError as exc:
        raise HelperError(_("The licence list could not be read.")) from exc
    entries = licences.validate_register(value)
    with locked(ADMIN_STATE):
        licences.write_register(ADMIN_STATE, entries)
        audit("licences", ngettext("The list of bought licences was changed (%d entry).",
                                   "The list of bought licences was changed (%d entries).", len(entries))
              % len(entries), count=len(entries))
    return {"count": len(entries)}


def ticket(stdin: str) -> dict[str, Any]:
    need(ADMIN)
    change = tickets.validate_change(read_object(stdin))
    with locked(ADMIN_STATE):
        changed = tickets.change(ADMIN_STATE, change, user())
        if changed is None:
            raise HelperError(_("Unknown ticket."))
        details = {key: value for key, value in change.items() if key in ("status", "assignee")}
        if "note" in change:
            details["note"] = "public" if change["note"]["public"] else "internal"
        audit("ticket", _("Ticket %s was changed.") % change["id"], ticket=change["id"], **details)
    return {"status": changed["status"]}


def read_object(stdin: str) -> dict[str, Any]:
    try:
        value = json.loads(stdin)
    except ValueError as exc:
        raise HelperError(_("The settings could not be read.")) from exc
    if not isinstance(value, dict):
        raise HelperError(_("The settings could not be read."))
    return value


def scope_title(scope: str, departments: dict[str, Any], machines: dict[str, Any]) -> str:
    if scope == "company":
        return _("the whole company")
    kind, _sep, key = scope.partition(":")
    if kind == "department":
        return _("department %s") % (departments.get(key) or {}).get("name", key)
    return _("machine %s") % admin.machine_name(machines, key)


def save_summary(found: list[tuple[str, str]], draft: dict[str, Any], machines: dict[str, Any]) -> str:
    if not found:
        return _("Settings saved without changes.")
    parts = []
    departments = draft.get("departments") or {}
    for scope, section in found:
        if section == "departments":
            parts.append(_("the departments"))
        elif section == "members":
            parts.append(_("who is in which department"))
        else:
            parts.append(f"{health.section_title(section)} ({scope_title(scope, departments, machines)})")
    return _("Settings saved: %s.") % ", ".join(parts)


def save(draft: dict[str, Any], passphrases: dict[str, str] | None = None) -> dict[str, Any]:
    """Saves a draft as the next policy; with locked(ADMIN_STATE)."""

    return admin.save_policy(draft, admin.ensure_key(ADMIN_KEY, ADMIN_STATE), hostname(), ADMIN_STATE,
                             box_private=admin.ensure_box_key(ADMIN_BOX_KEY), passphrases=passphrases)


def policy(stdin: str) -> dict[str, Any]:
    need(ADMIN)
    draft = read_object(stdin)
    pictures = draft.pop("pictures", None) or {}
    passphrases = draft.pop("wifi_passphrases", None) or {}
    if not isinstance(passphrases, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                    for k, v in passphrases.items()):
        raise HelperError(_("The settings could not be read."))
    with_pictures(draft, pictures)
    with locked(ADMIN_STATE):
        old = admin.draft_from_policy(admin.read_policy(ADMIN_STATE))
        saved = save(draft, passphrases)
        new = admin.draft_from_policy(saved)
        found = admin.changes(old, new)
        audit("settings", save_summary(found, new, admin.read_machines(ADMIN_STATE)), serial=saved["serial"],
              changes=[list(item) for item in found])
    admin.remove_unused_files(ADMIN_STATE)
    return {"serial": saved["serial"]}


def with_pictures(draft: dict[str, Any], pictures: Any) -> dict[str, Any]:
    """The draft with each picture picked since the last save ("new:N") copied in and named by its sha256, in every
    layer's wallpaper."""

    if not isinstance(pictures, dict) or len(pictures) > 4 * protocol.MAX_PERIODS:
        raise HelperError(_("The settings could not be read."))
    names: dict[str, str] = {}

    def resolve(value: Any) -> Any:
        if not (isinstance(value, str) and value.startswith("new:")):
            return value
        if value not in names:
            path = pictures.get(value)
            if not isinstance(path, str) or not path.startswith("/") or not Path(path).is_file():
                raise HelperError(_("A picture is missing: choose it again."))
            names[value] = admin.add_image(Path(path), ADMIN_STATE)["sha256"]
        return names[value]

    def fix(settings: Any) -> None:
        wallpaper = settings.get("wallpaper") if isinstance(settings, dict) else None
        if not isinstance(wallpaper, dict):
            return
        wallpaper["default"] = resolve(wallpaper.get("default"))
        for period in wallpaper.get("periods") or []:
            if isinstance(period, dict):
                period["image"] = resolve(period.get("image"))

    fix(draft.get("settings"))
    for group in ("departments", "machines"):
        for item in (draft.get(group) or {}).values():
            fix(item.get("settings") if isinstance(item, dict) else None)
    return draft


def machine_id_arg(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise HelperError(_("Unknown machine.")) from exc
    if str(parsed) != value:
        raise HelperError(_("Unknown machine."))
    return value


def forget_machine(machine_id: str) -> dict[str, Any]:
    need(ADMIN)
    machine_id_arg(machine_id)
    with locked(ADMIN_STATE):
        machines = admin.read_machines(ADMIN_STATE)
        name = admin.machine_name(machines, machine_id)
        removed = admin.forget_machine(machine_id, ADMIN_STATE, key=admin.ensure_key(ADMIN_KEY, ADMIN_STATE),
                                       admin_name=hostname(), by=user())
        if removed:
            current = admin.read_policy(ADMIN_STATE)
            if current.get("serial"):
                save(admin.draft_from_policy(current))  # its membership and sealed secrets go from the policy
            audit("forget", _("%s was taken out of the company.") % name, machine_id=machine_id, name=name)
    return {"removed": removed}


def targets_title(targets: dict[str, Any], policy_: dict[str, Any], machines: dict[str, Any]) -> str:
    departments = policy_.get("departments") or {}
    return summaries.targets_text(targets, lambda key: (departments.get(key) or {}).get("name", key),
                                  [admin.machine_name(machines, key) for key in targets.get("machines", [])])


def command(stdin: str) -> dict[str, Any]:
    need(ADMIN)
    request = read_object(stdin)
    if set(request) - {"targets", "action", "args", "help_id", "minutes"}:
        raise HelperError(_("The settings could not be read."))
    help_id = request.get("help_id")
    minutes = request.get("minutes")
    if minutes is not None and not (isinstance(minutes, int) and 1 <= minutes <= 24 * 60):
        raise HelperError(_("The settings could not be read."))
    with locked(ADMIN_STATE):
        machines = admin.read_machines(ADMIN_STATE)
        args = dict(request["args"]) if isinstance(request.get("args"), dict) else {}
        if request.get("action") == "remote_help":
            args["psk"] = sealed_remote_help_key(request.get("targets"), machines)
        try:
            queued = admin.queue_command(admin.ensure_key(ADMIN_KEY, ADMIN_STATE), request.get("targets"),
                                         request.get("action"), args, ADMIN_STATE, minutes=minutes)
        except protocol.ProtocolError as exc:
            raise HelperError(_("This action could not be sent: %s") % exc) from exc
        title = summaries.action_title(queued["action"])
        if queued["action"] == "message":
            title = f"{title} “{queued['args']['title']}”"
        audit("command", f"{title}: {targets_title(queued['targets'], admin.read_policy(ADMIN_STATE), machines)}.",
              command_id=queued["id"], command=queued["action"], targets=queued["targets"],
              args={key: value for key, value in queued["args"].items() if key in ("title", "minutes", "mode")},
              names=[admin.machine_name(machines, key) for key in queued["targets"].get("machines", [])])
        if isinstance(help_id, str) and protocol.TICKET_ID.match(help_id):
            current = tickets.find(tickets.read(ADMIN_STATE), help_id)
            if current is not None and current.get("status") == "new":
                tickets.change(ADMIN_STATE, {"id": help_id, "status": "working"}, user())
                audit("ticket", _("Ticket %s was answered with remote help.") % help_id, ticket=help_id,
                      status="working")
    return {"id": queued["id"], "seq": queued["seq"]}


def sealed_remote_help_key(targets: Any, machines: dict[str, Any]) -> str:
    """The session's pre-shared key, sealed for the one machine remote help goes to (PROTOCOL.md part 3)."""

    if not (isinstance(targets, dict) and list(targets) == ["machines"] and isinstance(targets["machines"], list)
            and len(targets["machines"]) == 1):
        raise HelperError(_("Remote help goes to one machine at a time."))
    machine_id = targets["machines"][0]
    entry = machines.get(machine_id)
    if not admin.approved(entry) or not entry.get("box_key"):
        raise HelperError(_("Unknown machine."))
    try:
        identity, key_hex = REMOTE_HELP_PSK.read_text(encoding="ascii").strip().split(":", 1)
    except (OSError, ValueError) as exc:
        raise HelperError(_("Remote help is not ready: press Connect again.")) from exc
    _mac, seal_key = protocol.machine_keys(admin.ensure_box_key(ADMIN_BOX_KEY), protocol.unb64(entry["box_key"], 32))
    return protocol.seal(seal_key, machine_id, {"identity": identity, "key": key_hex})


def asset(asset_id: str, stdin: str) -> dict[str, Any]:
    """An asset's details: a machine's (its id), or a thing without a machine (asset-<uuid4>)."""

    need(ADMIN)
    if not assets.ASSET_ID.match(asset_id):
        machine_id_arg(asset_id)
    with locked(ADMIN_STATE):
        machines = admin.read_machines(ADMIN_STATE)
        if not asset_id.startswith("asset-") and asset_id not in machines:
            raise HelperError(_("Unknown machine."))
        if asset_id.startswith("asset-") and asset_id not in admin.read_assets(ADMIN_STATE):
            raise HelperError(_("Unknown asset."))
        values = read_object(stdin)
        entry = assets.update(ADMIN_STATE, asset_id, values, user())
        name = assets.asset_name(asset_id, entry, machines)
        event = (values.get("add_event") or {}).get("event") if isinstance(values.get("add_event"), dict) else None
        if event == "handover":
            audit("asset", _("A handover document was printed for %s.") % name, machine_id=asset_id, name=name,
                  event="handover")
        else:
            audit("asset", _("The asset details of %s were changed.") % name, machine_id=asset_id, name=name)
    return {}


def asset_new(stdin: str) -> dict[str, Any]:
    need(ADMIN)
    with locked(ADMIN_STATE):
        asset_id, entry = assets.create(ADMIN_STATE, read_object(stdin), user())
        name = assets.asset_name(asset_id, entry, {})
        audit("asset", _("The asset %s was added.") % name, machine_id=asset_id, name=name, event="added")
    return {"id": asset_id}


def stunnel() -> str:
    for name in ("stunnel4", "stunnel"):
        found = shutil.which(name)
        if found:
            return found
    raise HelperError(_("Remote help needs the stunnel4 package."))


def viewer_rules(add: bool) -> None:
    """The rule that keeps the LAN off the viewer's port while remote help runs (vncviewer -listen binds every
    interface): one for IPv4 and one for IPv6, deleted again at the end. Raises when the IPv4 rule cannot be added."""

    rule = ["INPUT", "-p", "tcp", "--dport", str(VIEWER_PORT), "!", "-i", "lo", "-m", "comment", "--comment",
            REMOTE_HELP_RULE, "-j", "DROP"]
    for tool in ("iptables", "ip6tables"):
        program = shutil.which(tool) or (f"/usr/sbin/{tool}" if Path(f"/usr/sbin/{tool}").exists() else None)
        if program is None:
            if add and tool == "iptables":
                raise HelperError(_("Remote help needs the iptables program, to keep the network off the viewer."))
            continue
        for _attempt in range(8):  # rules a crashed session left behind
            if subprocess.run([program, "-D", *rule], capture_output=True, timeout=30, check=False).returncode != 0:
                break
        if add:
            done = subprocess.run([program, "-I", *rule], capture_output=True, text=True, timeout=30, check=False)
            if done.returncode != 0 and tool == "iptables":
                raise HelperError(_("Remote help could not close the viewer's port to the network: %s")
                                  % done.stderr.strip())


def remote_help(action: str) -> dict[str, Any]:
    need(ADMIN)
    unit = f"{REMOTE_HELP_UNIT}.service"
    if action == "start":
        program = stunnel()
        RUN.mkdir(parents=True, exist_ok=True)
        identity = f"rh-{secrets.token_hex(8)}"
        write_atomic(REMOTE_HELP_PSK, f"{identity}:{secrets.token_hex(32)}\n".encode("ascii"), mode=0o600)
        write_atomic(REMOTE_HELP_CONF, (
            "; CaramOS Doanh nghiệp: remote help. TLS 1.3 with a key for this session on port %d, to the viewer that\n"
            "; listens on 127.0.0.1:%d. Made by caramos-business-helper; removed when remote help stops.\n"
            "foreground = yes\npid =\nsyslog = no\ndebug = notice\n\n[remote-help]\naccept = 0.0.0.0:%d\n"
            "connect = 127.0.0.1:%d\nPSKsecrets = %s\nciphers = PSK\nciphersuites = TLS_AES_128_GCM_SHA256\n"
            "sslVersionMin = TLSv1.3\n" % (REMOTE_HELP_PORT, VIEWER_PORT, REMOTE_HELP_PORT, VIEWER_PORT,
                                           REMOTE_HELP_PSK)
        ).encode("utf-8"), mode=0o600)
        viewer_rules(True)
        subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=30, check=False)
        subprocess.run(["systemctl", "reset-failed", unit], capture_output=True, timeout=30, check=False)
        result = subprocess.run(["systemd-run", f"--unit={REMOTE_HELP_UNIT}", "--collect",
                                 "--description=CaramOS Business remote help",
                                 "-p", "RuntimeMaxSec=4h", "-p", "NoNewPrivileges=yes", "-p", "ProtectHome=yes",
                                 "-p", "PrivateTmp=yes", program, str(REMOTE_HELP_CONF)],
                                capture_output=True, text=True, timeout=60, check=False)
        if result.returncode != 0:
            viewer_rules(False)
            raise HelperError(_("Remote help could not start: %s") % result.stderr.strip())
        if ufw_active():
            ufw("allow", f"{REMOTE_HELP_PORT}/tcp")
        return {"port": REMOTE_HELP_PORT}
    if action == "stop":
        subprocess.run(["systemctl", "stop", unit], capture_output=True, timeout=30, check=False)
        REMOTE_HELP_CONF.unlink(missing_ok=True)
        REMOTE_HELP_PSK.unlink(missing_ok=True)
        viewer_rules(False)
        if ufw_active():
            ufw("delete", "allow", f"{REMOTE_HELP_PORT}/tcp")
        return {}
    raise HelperError("start or stop")


@contextlib.contextmanager
def as_invoker() -> Iterator[None]:
    """Acts as the user who ran the window (PKEXEC_UID) for opening a file they chose: root writes nowhere the user
    could not."""

    uid = os.environ.get("PKEXEC_UID")
    if os.geteuid() != 0 or not uid:
        yield
        return
    account = pwd.getpwuid(int(uid))
    saved_groups = os.getgroups()
    os.setgroups(os.getgrouplist(account.pw_name, account.pw_gid))
    os.setegid(account.pw_gid)
    os.seteuid(account.pw_uid)
    try:
        yield
    finally:
        os.seteuid(0)
        os.setegid(0)
        os.setgroups(saved_groups)


def file_arg(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or "\0" in value or len(value) > 4096:
        raise HelperError(_("Choose a file."))
    return path


def make_backup(target: str, stdin: str) -> dict[str, Any]:
    need(ADMIN)
    path = file_arg(target)
    passphrase = stdin.rstrip("\n")
    with locked(ADMIN_STATE):
        try:
            blob = backup.make_backup(passphrase, ETC, ADMIN_STATE)
        except backup.BackupError as exc:
            raise HelperError(str(exc)) from exc
        with as_invoker():
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(blob)
            except OSError as exc:
                raise HelperError(_("Could not write %(file)s: %(error)s") % {"file": path, "error": exc.strerror}) \
                    from exc
        audit("backup", _("A backup was made: %s.") % path.name, file=path.name)
    return {"size": len(blob)}


def restore(source: str, stdin: str) -> dict[str, Any]:
    if role() is not None:
        raise HelperError(_("Only a machine without a role can take over from a backup."))
    path = file_arg(source)
    with as_invoker():
        try:
            if path.stat().st_size > backup.MAX_BACKUP:
                raise HelperError(_("This is not a CaramOS Business backup."))
            blob = path.read_bytes()
        except OSError as exc:
            raise HelperError(_("Could not read %(file)s: %(error)s") % {"file": path, "error": exc.strerror}) from exc
    admin.prepare_state(ADMIN_STATE)
    try:
        backup.restore(blob, stdin.rstrip("\n"), ETC, ADMIN_STATE)
    except backup.BackupError as exc:
        raise HelperError(str(exc)) from exc
    ensure_admin()
    open_firewall()
    write_atomic(ROLE_FILE, b"admin\n")
    systemctl("enable", SERVER_UNIT)
    systemctl("restart", SERVER_UNIT)
    audit("restore", _("This machine took over as the admin machine from a backup."))
    return {"role": ADMIN}


def write_pairing(config: dict[str, str], box_private: bytes, state: str, start: bool = True) -> dict[str, Any]:
    """What pairing leaves on an employee machine (PROTOCOL.md parts 2 and 3), then the agent starts (unless start is
    false: enroll-on-boot starts it itself)."""

    # This disk's machine id: a disk cloned from here later carries the pairing, and the agent then stops
    # (PROTOCOL.md part 2 "Cloned disks").
    machine_id_os = client.os_machine_id(OS_MACHINE_ID)
    if machine_id_os:
        config["machine_id_os"] = machine_id_os
    write_atomic(AGENT_BOX_KEY, box_private, mode=0o600)
    write_atomic(ROLE_FILE, b"employee\n")
    write_json(AGENT_CONFIG, config, mode=0o600)
    AGENT_STATE.mkdir(parents=True, exist_ok=True)
    os.chmod(AGENT_STATE, 0o755)
    for name in ("clone.json", "removed.json", "enroll-failed.json"):
        (AGENT_STATE / name).unlink(missing_ok=True)
    public = {"admin_name": config["admin_name"], "admin_url": config["admin_url"],
              "fingerprint": config["fingerprint"], "machine_id": config["machine_id"]}
    if machine_id_os:
        public["machine_id_os"] = machine_id_os
    write_json(PUBLIC_AGENT_INFO, public)
    write_json(AGENT_STATE / "approval.json", {"state": state, "since": admin.now_iso()})
    if start:
        systemctl("enable", AGENT_UNIT)
        systemctl("restart", AGENT_UNIT)
    return {"admin_name": config["admin_name"], "state": state}


def pair(ip: str, code: str) -> dict[str, Any]:
    if role() not in (None, EMPLOYEE):
        raise HelperError(_("This machine is the admin machine already."))
    try:
        socket.inet_aton(ip)
    except OSError as exc:
        raise HelperError(_("Not an IPv4 address.")) from exc
    box_private = protocol.new_box_key()
    try:
        config, state = client.pair(ip, code, box_private)
    except client.PairingError as exc:
        raise HelperError(str(exc)) from exc
    return write_pairing(config, box_private, state)


def read_enroll_file(path: Path, *, as_user: bool = True) -> dict[str, Any]:
    """An enrolment file, read as the user who ran the window, and checked."""

    try:
        with as_invoker() if as_user else contextlib.nullcontext():
            if path.stat().st_size > protocol.MAX_BODY:
                raise HelperError(_("This is not an enrolment file."))
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise HelperError(_("This is not an enrolment file.")) from exc
    try:
        return protocol.validate_enroll_file(data)
    except protocol.ProtocolError as exc:
        raise HelperError(str(exc)) from exc


def pair_with_file(data: dict[str, Any]) -> dict[str, Any]:
    box_private = protocol.new_box_key()
    try:
        config, state = client.enroll(data, box_private)
    except client.PairingError as exc:
        raise HelperError(str(exc)) from exc
    return write_pairing(config, box_private, state)


def pair_file(source: str) -> dict[str, Any]:
    if role() not in (None, EMPLOYEE):
        raise HelperError(_("This machine is the admin machine already."))
    return pair_with_file(read_enroll_file(file_arg(source)))


def frozen(mounts: Path | None = None) -> bool:
    """Whether / is overlayroot now (shared-machine mode, PROTOCOL.md part 3)."""

    try:
        lines = (mounts or PROC_MOUNTS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(len(fields) >= 3 and fields[1] == "/" and fields[2] == "overlay" for fields in map(str.split, lines))


def prepare_image(stdin: str) -> dict[str, Any]:
    """Prepares a machine whose disk will be copied (PROTOCOL.md part 3): it leaves the company, forgets its identity
    (pairing, machine id, SSH host keys) and, with an enrolment file, enrols each copy at its first boot."""

    if role() not in (None, EMPLOYEE):
        raise HelperError(_("This machine is the admin machine already."))
    if frozen():
        raise HelperError(_("Turn off freezing first."))
    request = read_object(stdin) if stdin.strip() else {}
    source = request.get("enroll_file")
    data = read_enroll_file(file_arg(source)) if source else None
    if AGENT_CONFIG.exists():
        leave()
    AGENT_CONFIG.unlink(missing_ok=True)
    AGENT_BOX_KEY.unlink(missing_ok=True)
    if AGENT_STATE.is_dir():
        shutil.rmtree(AGENT_STATE)
    write_atomic(OS_MACHINE_ID, b"", mode=0o444)
    if DBUS_MACHINE_ID.is_file() and not DBUS_MACHINE_ID.is_symlink():
        DBUS_MACHINE_ID.unlink()
    if (SSH_DIR / "sshd_config").exists():
        for key in SSH_DIR.glob("ssh_host_*"):
            key.unlink()
    if data is not None:
        write_json(ENROLL_ON_BOOT, data, mode=0o600)
        systemctl("enable", HOSTNAME_UNIT, ENROLL_UNIT)
    else:
        ENROLL_ON_BOOT.unlink(missing_ok=True)
        disable_enrol_units()
    write_atomic(ROLE_FILE, b"employee\n")
    return {"enroll": data is not None}


def set_hostname(prefix: str) -> str:
    """<prefix>-<first 6 hex digits of the machine id>, through hostnamectl and the 127.0.1.1 line of /etc/hosts."""

    machine_id = client.os_machine_id(OS_MACHINE_ID)
    if not machine_id:
        raise HelperError("no machine id yet")
    name = f"{prefix}-{machine_id[:6]}"
    if socket.gethostname() != name:
        subprocess.run(["hostnamectl", "set-hostname", name], capture_output=True, timeout=60, check=False)
    try:
        text = HOSTS.read_text(encoding="utf-8")
    except OSError:
        text = ""
    lines = [line for line in text.splitlines() if not line.startswith("127.0.1.1")]
    write_atomic(HOSTS, ("\n".join([*lines, f"127.0.1.1\t{name}"]) + "\n").encode("utf-8"), mode=0o644)
    return name


def disable_enrol_units() -> None:
    # Never a blocking start or stop from these units: the agent is ordered after them.
    subprocess.run(["systemctl", "disable", HOSTNAME_UNIT, ENROLL_UNIT], capture_output=True, timeout=60, check=False)


def enroll_hostname() -> dict[str, Any]:
    """caramos-business-hostname.service: the copy's own host name, set before the display manager starts. The
    enrolment waits for the network, which comes up about when LightDM starts its X server; a name changed after that
    locks the session's programs out of the display (the X cookie is filed under the old name)."""

    if os.environ.get("PKEXEC_UID"):
        raise HelperError("enroll-hostname runs from caramos-business-hostname.service only")
    try:
        data = read_enroll_file(ENROLL_ON_BOOT, as_user=False)
    except HelperError:
        return {"hostname": None}  # enroll-on-boot gives up on this file and says why
    prefix = data.get("hostname_prefix")
    return {"hostname": set_hostname(prefix) if prefix else None}


def enroll_on_boot() -> dict[str, Any]:
    """caramos-business-enroll.service: a copy of a prepared disk enrols itself at its first boot (PROTOCOL.md
    part 3). Raising makes the unit try again a minute later; a refused token gives up for good."""

    if os.environ.get("PKEXEC_UID"):
        raise HelperError("enroll-on-boot runs from caramos-business-enroll.service only")
    if (SSH_DIR / "sshd_config").exists() and not any(SSH_DIR.glob("ssh_host_*_key")):
        new_ssh_keys()
    if not ENROLL_ON_BOOT.exists():
        return {"enrolled": False}

    def give_up(error: str) -> dict[str, Any]:
        AGENT_STATE.mkdir(parents=True, exist_ok=True)
        write_json(AGENT_STATE / "enroll-failed.json", {"time": admin.now_iso(), "error": error})
        ENROLL_ON_BOOT.unlink(missing_ok=True)
        disable_enrol_units()
        return {"enrolled": False, "error": error}

    try:
        data = read_enroll_file(ENROLL_ON_BOOT, as_user=False)
    except HelperError as exc:
        return give_up(str(exc))
    if role() is None:
        write_atomic(ROLE_FILE, b"employee\n")
    if data.get("hostname_prefix"):
        set_hostname(data["hostname_prefix"])  # the same name: caramos-business-hostname.service set it already
    box_private = protocol.new_box_key()
    try:
        config, state = client.enroll(data, box_private)
    except client.TokenRefused as exc:
        return give_up(str(exc))
    except client.PairingError as exc:
        raise HelperError(str(exc)) from exc
    result = write_pairing(config, box_private, state, start=False)
    # The file goes before anything else can fail: a second run would enrol the machine again, with another use.
    ENROLL_ON_BOOT.unlink(missing_ok=True)
    disable_enrol_units()
    # --no-block: this unit runs Before= the agent, whose start job waits for this unit to end.
    subprocess.run(["systemctl", "enable", AGENT_UNIT], capture_output=True, timeout=60, check=False)
    subprocess.run(["systemctl", "--no-block", "restart", AGENT_UNIT], capture_output=True, timeout=60, check=False)
    return dict(result, enrolled=True)


def new_ssh_keys() -> None:
    """The SSH host keys prepare-image removed, made anew, and sshd listening again: with socket activation (Ubuntu
    24.04's default), the socket failed at boot while the keys were missing, and a try-restart starts nothing."""

    subprocess.run(["ssh-keygen", "-A"], capture_output=True, timeout=120, check=False)
    subprocess.run(["systemctl", "reset-failed", "ssh.socket", "ssh.service"], capture_output=True, timeout=60,
                   check=False)
    for unit in ("ssh.socket", "ssh.service"):
        enabled = subprocess.run(["systemctl", "is-enabled", unit], capture_output=True, text=True, timeout=60,
                                 check=False).stdout.strip()
        if enabled == "enabled":
            subprocess.run(["systemctl", "--no-block", "restart", unit], capture_output=True, timeout=60, check=False)
            break


def leave() -> dict[str, Any]:
    need(EMPLOYEE)
    # The agent puts back what it changed (PROTOCOL.md parts 2 and 3); on a frozen machine it finishes at the next
    # boot and says "reboot needed".
    reboot = False
    if Path(AGENT).exists():
        done = subprocess.run([AGENT, "leave"], capture_output=True, text=True, timeout=180, check=False)
        reboot = "reboot needed" in done.stdout
    subprocess.run(["systemctl", "disable", "--now", AGENT_UNIT], capture_output=True, timeout=60, check=False)
    AGENT_CONFIG.unlink(missing_ok=True)
    AGENT_BOX_KEY.unlink(missing_ok=True)
    # Without a policy the session part gives each user their own Desktop and Documents back. The pictures stay:
    # the wallpaper keeps showing the company's last one (removing them left a blank desktop), and purging the package
    # removes them.
    for name in ("policy.json", "admin.json", "clone.json", "approval.json", "removed.json", "enroll-failed.json"):
        (AGENT_STATE / name).unlink(missing_ok=True)
    return {"reboot": reboot}


def run(argv: list[str], stdin: str = "") -> dict[str, Any]:
    if argv[:1] == ["role"] and len(argv) == 2:
        return set_role(argv[1])
    if argv[:1] == ["pairing"] and len(argv) == 2:
        return pairing(argv[1])
    if argv == ["options"]:
        return options(stdin)
    if argv[:1] == ["approve"] and len(argv) == 2:
        return approve(argv[1])
    if argv[:1] == ["reject"] and len(argv) == 2:
        return reject(argv[1])
    if argv[:1] == ["enroll-token"] and len(argv) == 3 and argv[1] in ("create", "revoke"):
        return enroll_token(argv[1], argv[2], stdin)
    if argv == ["licences"]:
        return licences_command(stdin)
    if argv == ["ticket"]:
        return ticket(stdin)
    if argv == ["asset-new"]:
        return asset_new(stdin)
    if argv == ["policy"]:
        return policy(stdin)
    if argv == ["command"]:
        return command(stdin)
    if argv[:1] == ["forget-machine"] and len(argv) == 2:
        return forget_machine(argv[1])
    if argv[:1] == ["asset"] and len(argv) == 2:
        return asset(argv[1], stdin)
    if argv[:1] == ["remote-help"] and len(argv) == 2:
        return remote_help(argv[1])
    if argv[:1] == ["backup"] and len(argv) == 2:
        return make_backup(argv[1], stdin)
    if argv[:1] == ["restore"] and len(argv) == 2:
        return restore(argv[1], stdin)
    if argv[:1] == ["pair"] and len(argv) == 3:
        return pair(argv[1], argv[2])
    if argv[:1] == ["pair-file"] and len(argv) == 2:
        return pair_file(argv[1])
    if argv == ["prepare-image"]:
        return prepare_image(stdin)
    if argv == ["enroll-hostname"]:
        return enroll_hostname()
    if argv == ["enroll-on-boot"]:
        return enroll_on_boot()
    if argv == ["leave"]:
        return leave()
    raise HelperError("usage: see caramos_business/helper.py")


STDIN_COMMANDS = {"policy": MAX_POLICY_INPUT, "command": protocol.MAX_BODY, "asset": protocol.MAX_BODY,
                  "asset-new": protocol.MAX_BODY, "backup": 4096, "restore": 4096, "options": 4096,
                  "enroll-token": 4096, "licences": protocol.MAX_BODY, "ticket": protocol.MAX_BODY,
                  "prepare-image": 8192}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "error": "run through pkexec"}))
        return 1
    limit = STDIN_COMMANDS.get(argv[0]) if argv else None
    stdin = sys.stdin.read(limit) if limit else ""
    try:
        result = run(argv, stdin)
    except (HelperError, protocol.ProtocolError, backup.BackupError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc), **error_place(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(dict(result, ok=True), ensure_ascii=False))
    return 0


def error_place(exc: Exception) -> dict[str, str]:
    """Where a settings error is, for the window: the section and the scope."""

    place = {}
    for key in ("section", "scope"):
        value = getattr(exc, key, None)
        if value:
            place[key] = value
    return place

