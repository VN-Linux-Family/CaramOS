"""Helpdesk tickets (PROTOCOL.md part 3, "Helpdesk tickets"): tickets.json on the admin, the ticket an employee's
"Nhờ IT hỗ trợ" makes, the admin's changes, and the list each machine fetches (signed, public notes only).

A machine's version moves whenever its employees would see a difference (a status, a public note): /wait tells the
agent the version, and the agent fetches GET /tickets when it moved."""

from __future__ import annotations

import datetime
import statistics
from pathlib import Path
from typing import Any

from . import protocol
from .i18n import _
from .store import read_json, write_json

TICKETS = "tickets.json"
MAX_OPEN_PER_MACHINE = 20
MAX_SHOWN = 50              # tickets in a machine's list
SHOWN_DAYS = 30             # closed tickets stay in a machine's list this long
MAX_UPDATES = 20
MAX_TEXT = 500
MAX_NOTES = 200
STATUS_NAMES = {"new": "Mới", "working": "Đang xử lý", "waiting": "Chờ bạn trả lời", "done": "Đã xong"}


def now_iso(now: datetime.datetime | None = None) -> str:
    return (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds")


def parse(text: Any) -> datetime.datetime | None:
    try:
        value = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.astimezone()


def read(state: Path) -> dict[str, Any]:
    store = read_json(state / TICKETS, {})
    if not isinstance(store, dict):
        store = {}
    tickets = [item for item in store.get("tickets", []) if isinstance(item, dict)]
    versions = store.get("versions") if isinstance(store.get("versions"), dict) else {}
    return {"next": store.get("next") if isinstance(store.get("next"), int) else 1, "versions": dict(versions),
            "tickets": tickets}


def write(state: Path, store: dict[str, Any]) -> None:
    write_json(state / TICKETS, store)


def version(store: dict[str, Any], machine_id: str) -> int:
    value = store["versions"].get(machine_id, 0)
    return value if isinstance(value, int) else 0


def _bump(store: dict[str, Any], machine_id: str) -> int:
    store["versions"][machine_id] = version(store, machine_id) + 1
    return store["versions"][machine_id]


def find(store: dict[str, Any], ticket_id: str) -> dict[str, Any] | None:
    return next((item for item in store["tickets"] if item.get("id") == ticket_id), None)


def inventory_summary(inventory: dict[str, Any] | None) -> dict[str, Any]:
    """What a ticket keeps of the machine's inventory: model, CPU, memory, disks, CaramOS version."""

    inventory = inventory or {}
    system = inventory.get("system") or {}
    return {"model": " ".join(part for part in (system.get("vendor"), system.get("product")) if part),
            "cpu": (inventory.get("cpu") or {}).get("model", ""),
            "memory_mb": (inventory.get("memory") or {}).get("total_mb"),
            "disks": [{"model": disk.get("model", ""), "size_gb": disk.get("size_gb"), "health": disk.get("health")}
                      for disk in inventory.get("disks") or []][:8],
            "caramos": (inventory.get("os") or {}).get("caramos", "")}


def create(state: Path, machine_id: str, request: dict[str, Any], health: Any, inventory: dict[str, Any] | None,
           now: datetime.datetime | None = None) -> tuple[dict[str, Any], int]:
    """A ticket from POST /help (validated by protocol.validate_help); (ticket, the machine's new version). A machine
    has at most MAX_OPEN_PER_MACHINE open tickets: the oldest open one closes first. Call it with locked(state)."""

    store = read(state)
    mine = [item for item in store["tickets"] if item.get("machine_id") == machine_id and item.get("status") != "done"]
    for old in mine[:max(0, len(mine) - MAX_OPEN_PER_MACHINE + 1)]:
        old["status"], old["closed"] = "done", now_iso(now)
    ticket = {"id": f"HT-{store['next']:04d}", "machine_id": machine_id, "user": request.get("user", ""),
              "note": request.get("note", ""), "created": now_iso(now), "status": "new", "assignee": "",
              "first_response": None, "closed": None, "notes": [],
              "snapshot": {"health": health if isinstance(health, dict) else {},
                           "inventory_summary": inventory_summary(inventory)}}
    store["next"] += 1
    store["tickets"].append(ticket)
    new_version = _bump(store, machine_id)
    write(state, store)
    return ticket, new_version


def validate_change(change: Any) -> dict[str, Any]:
    """The helper's `ticket`: {"id", "status"?, "assignee"?, "note"?: {"text", "public"}}."""

    if not isinstance(change, dict) or not isinstance(change.get("id"), str) or \
            not protocol.TICKET_ID.match(change["id"]):
        raise protocol.ProtocolError(_("The ticket change could not be read."))
    result: dict[str, Any] = {"id": change["id"]}
    if "status" in change:
        if change["status"] not in protocol.TICKET_STATES:
            raise protocol.ProtocolError(_("The ticket change could not be read."))
        result["status"] = change["status"]
    if "assignee" in change:
        if not protocol._clean_text(change["assignee"], 60):  # noqa: SLF001 - the same rule
            raise protocol.ProtocolError(_("A name has at most 60 characters."))
        result["assignee"] = change["assignee"].strip()
    if "note" in change:
        note = change["note"]
        if not (isinstance(note, dict) and isinstance(note.get("public"), bool)
                and protocol._clean_text(note.get("text"), MAX_TEXT, empty=False, newlines=True)):  # noqa: SLF001
            raise protocol.ProtocolError(_("A note has 1 to 500 characters."))
        result["note"] = {"text": note["text"].strip(), "public": note["public"]}
    return result


def change(state: Path, change: dict[str, Any], by: str, now: datetime.datetime | None = None) -> dict[str, Any] | None:
    """Applies a validated change; the ticket, or None when there is no such ticket. The first public note or status
    change sets first_response; done sets closed. Call it with locked(state)."""

    store = read(state)
    ticket = find(store, change["id"])
    if ticket is None:
        return None
    seen = False
    status = change.get("status")
    if status and status != ticket.get("status"):
        ticket["status"] = status
        ticket["closed"] = now_iso(now) if status == "done" else None
        seen = True
    if "assignee" in change:
        ticket["assignee"] = change["assignee"]
    note = change.get("note")
    if note or (status and seen):
        entry = {"time": now_iso(now), "by": by, "text": note["text"] if note else "",
                 "public": bool(note["public"]) if note else True}
        if status and seen:
            entry["status"] = status
        ticket.setdefault("notes", []).append(entry)
        ticket["notes"] = ticket["notes"][-MAX_NOTES:]
        seen = seen or bool(note and note["public"])
    if seen:
        if not ticket.get("first_response"):
            ticket["first_response"] = now_iso(now)
        _bump(store, ticket["machine_id"])
    write(state, store)
    return ticket


def machine_list(store: dict[str, Any], machine_id: str, now: datetime.datetime | None = None) -> dict[str, Any]:
    """What GET /tickets signs for a machine: its open tickets and those closed in the last SHOWN_DAYS, at most
    MAX_SHOWN, with the public notes and status changes as updates. Internal notes never leave the admin."""

    now = now or datetime.datetime.now().astimezone()
    shown = []
    for ticket in store["tickets"]:
        if ticket.get("machine_id") != machine_id:
            continue
        closed = parse(ticket.get("closed"))
        if ticket.get("status") == "done" and closed and now - closed > datetime.timedelta(days=SHOWN_DAYS):
            continue
        updates = []
        for note in ticket.get("notes") or []:
            if not note.get("public", False):
                continue
            update = {"time": note.get("time", ""), "text": (note.get("text") or "")[:MAX_TEXT]}
            if note.get("status"):
                update["status"] = note["status"]
            updates.append(update)
        shown.append({"id": ticket["id"], "user": ticket.get("user", ""), "created": ticket.get("created", ""),
                      "status": ticket.get("status", "new"), "note": ticket.get("note", ""),
                      "updates": updates[-MAX_UPDATES:]})
    return {"kind": "tickets", "machine_id": machine_id, "version": version(store, machine_id), "issued": now_iso(now),
            "tickets": shown[-MAX_SHOWN:]}


def month_report(store: dict[str, Any], year: int, month: int) -> dict[str, Any]:
    """The monthly figures: counts by status of the tickets made that month, the median minutes to the first
    response, and the list."""

    made = [ticket for ticket in store["tickets"]
            if (created := parse(ticket.get("created"))) and created.year == year and created.month == month]
    counts = {state: sum(1 for ticket in made if ticket.get("status") == state) for state in protocol.TICKET_STATES}
    waits = []
    for ticket in made:
        created, first = parse(ticket.get("created")), parse(ticket.get("first_response"))
        if created and first:
            waits.append((first - created).total_seconds() / 60)
    return {"counts": counts, "total": len(made), "median_first_response_minutes":
            round(statistics.median(waits)) if waits else None, "tickets": made}
