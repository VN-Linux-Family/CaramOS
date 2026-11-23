"""The asset list's lifecycle (PROTOCOL.md part 3, "Asset lifecycle and handover"): assets.json holds a machine's
asset details under its machine id, and things without a machine (a machine not paired, a monitor, a printer) under
asset-<uuid4>. Each entry has a status, a holder since a date, and a history the helper writes when the status or
the holder changes; the window adds notes, handovers and the steps of "Nhân viên nghỉ việc"."""

from __future__ import annotations

import datetime
import re
import uuid
from pathlib import Path
from typing import Any

from . import admin, protocol
from .i18n import _
from .store import write_json

ASSET_ID = re.compile(r"^asset-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
KINDS = admin.ASSET_KINDS
STATES = admin.ASSET_STATES
EVENTS = admin.ASSET_EVENTS
LEAVER_STEPS = ("returned", "archived", "department", "in_stock")
WARRANTY_DAYS = 30


def validate(values: Any, *, machine_id: str | None) -> dict[str, Any]:
    """An entry as the window sends it: part 2's fields, plus kind, status, holder_since, the name of a thing without
    a machine, the steps of "Nhân viên nghỉ việc" done so far, and an optional event to add to the history."""

    base = admin.validate_asset(values)
    result: dict[str, Any] = dict(base, machine_id=machine_id)
    kind = values.get("kind", "computer")
    status = values.get("status", "in_use" if machine_id else "in_stock")
    if kind not in KINDS or status not in STATES:
        raise protocol.ProtocolError(_("The asset details could not be read."))
    result["kind"], result["status"] = kind, status
    since = values.get("holder_since", "")
    if not admin._date_or_empty(since):  # noqa: SLF001 - the same rule
        raise protocol.ProtocolError(_("Write dates as day/month/year, such as 15/3/2024."))
    result["holder_since"] = since
    if machine_id is None:
        name = values.get("name", "")
        if not protocol._clean_text(name, 100, empty=False):  # noqa: SLF001
            raise protocol.ProtocolError(_("Give the asset a name of at most 100 characters."))
        result["name"] = name.strip()
    leaver = values.get("leaver")
    if leaver is not None:
        if not (isinstance(leaver, list) and all(step in LEAVER_STEPS for step in leaver)):
            raise protocol.ProtocolError(_("The asset details could not be read."))
        result["leaver"] = list(dict.fromkeys(leaver))
    event = values.get("add_event")
    if event is not None:
        if not (isinstance(event, dict) and event.get("event") in EVENTS
                and protocol._clean_text(event.get("note", ""), 300, newlines=True)):  # noqa: SLF001
            raise protocol.ProtocolError(_("The asset details could not be read."))
        result["add_event"] = {"event": event["event"], "note": event.get("note", "").strip()}
    return result


def _event(entry: dict[str, Any], event: str, by: str, note: str, now: datetime.datetime | None) -> None:
    history = [item for item in entry.get("history") or [] if isinstance(item, dict)]
    history.append({"time": admin.now_iso(now), "event": event, "by": by, "note": note})
    entry["history"] = history[-admin.MAX_HISTORY:]


def update(state: Path, asset_id: str, values: Any, by: str, now: datetime.datetime | None = None) -> dict[str, Any]:
    """Saves an entry; a status or holder change goes into its history. Call it with locked(state)."""

    stored = admin.read_assets(state)
    old = stored.get(asset_id) if isinstance(stored.get(asset_id), dict) else {}
    new = validate(values, machine_id=None if asset_id.startswith("asset-") else asset_id)
    event = new.pop("add_event", None)
    new["history"] = list(old.get("history") or [])
    if old and old.get("status", new["status"]) != new["status"]:
        kinds = {"repair": "repair", "disposed": "disposed", "in_stock": "returned", "in_use": "assigned"}
        _event(new, kinds[new["status"]], by, "", now)
    if old.get("holder", "") != new["holder"] and new["holder"]:
        if not new["holder_since"] or new["holder_since"] == old.get("holder_since"):
            new["holder_since"] = (now or datetime.datetime.now().astimezone()).date().isoformat()
        _event(new, "assigned", by, new["holder"], now)
    if event:
        _event(new, event["event"], by, event["note"], now)
    stored[asset_id] = new
    write_json(state / admin.ASSETS, stored)
    return new


def create(state: Path, values: Any, by: str, now: datetime.datetime | None = None) -> tuple[str, dict[str, Any]]:
    """A thing without a machine; (asset-<uuid4>, entry). Call it with locked(state)."""

    asset_id = f"asset-{uuid.uuid4()}"
    entry = validate(values, machine_id=None)
    entry.pop("add_event", None)
    entry["history"] = []
    _event(entry, "received", by, "", now)
    stored = admin.read_assets(state)
    stored[asset_id] = entry
    write_json(state / admin.ASSETS, stored)
    return asset_id, entry


def asset_name(asset_id: str, entry: dict[str, Any] | None, machines: dict[str, Any]) -> str:
    if asset_id.startswith("asset-"):
        return (entry or {}).get("name") or asset_id[6:14]
    return admin.machine_name(machines, asset_id)


def rows(machines: dict[str, Any], stored: dict[str, Any]) -> list[dict[str, Any]]:
    """Every asset, machines first (sorted by name), then the things without a machine: {"id", "name", "entry"}."""

    found = []
    for machine_id in sorted(machines, key=lambda key: admin.machine_name(machines, key)):
        entry = stored.get(machine_id) if isinstance(stored.get(machine_id), dict) else {}
        found.append({"id": machine_id, "name": admin.machine_name(machines, machine_id),
                      "entry": dict({"kind": "computer", "status": "in_use"}, **entry)})
    others = [(key, value) for key, value in stored.items() if ASSET_ID.match(key) and isinstance(value, dict)]
    for asset_id, entry in sorted(others, key=lambda item: item[1].get("name", "")):
        found.append({"id": asset_id, "name": asset_name(asset_id, entry, machines), "entry": entry})
    return found


def warranty_ending(stored: dict[str, Any], today: datetime.date, days: int = WARRANTY_DAYS) -> list[str]:
    """The assets whose warranty ends within days (not those already ended)."""

    ending = []
    for asset_id, entry in stored.items():
        try:
            until = datetime.date.fromisoformat((entry or {}).get("warranty_until", ""))
        except (TypeError, ValueError):
            continue
        if today <= until <= today + datetime.timedelta(days=days) and entry.get("status") != "disposed":
            ending.append(asset_id)
    return ending


def in_repair(stored: dict[str, Any]) -> list[str]:
    return [asset_id for asset_id, entry in stored.items() if isinstance(entry, dict) and entry.get("status") == "repair"]
