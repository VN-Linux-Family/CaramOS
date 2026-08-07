"""Persistent state handling for CaramOS OTA."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from typing import Any

from .constants import STATE_DIR, STATE_FILE


def default_state() -> dict[str, Any]:
    """Return a fresh state object."""

    return {
        "schema": 2,
        "last_check": None,
        "last_successful_upgrade": None,
        "installed_release": None,
        "available_update": None,
        "transaction": None,
        "transactions": [],
    }


def _upgrade_state(state: dict[str, Any]) -> dict[str, Any]:
    schema = state.get("schema")
    if schema == 1:
        state["schema"] = 2
        state.setdefault("transaction", None)
    elif schema != 2:
        raise ValueError("unsupported state schema")
    state.setdefault("last_check", None)
    state.setdefault("last_successful_upgrade", None)
    state.setdefault("installed_release", state.pop("installed_version", None))
    state.setdefault("available_update", None)
    state.setdefault("transaction", None)
    state.setdefault("transactions", [])
    if not isinstance(state["transactions"], list):
        state["transactions"] = []
    return state


def load_state() -> dict[str, Any]:
    """Load state.json, upgrading v1 and backing up corrupt state."""

    if STATE_FILE.exists():
        try:
            with STATE_FILE.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
            if not isinstance(state, dict):
                raise ValueError("state root is not an object")
            original_schema = state.get("schema")
            upgraded = _upgrade_state(state)
            if original_schema == 1:
                save_state(upgraded)
            return upgraded
        except Exception:
            backup = STATE_FILE.with_name(f"{STATE_FILE.name}.corrupt.{int(datetime.now().timestamp())}")
            try:
                shutil.copy2(STATE_FILE, backup)
            except OSError:
                pass
    state = default_state()
    save_state(state)
    return state


def save_state(state: dict[str, Any]) -> None:
    """Atomically write state.json with user-readable permissions."""

    state = _upgrade_state(state)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = STATE_FILE.with_suffix(".json.tmp")
    with temp_file.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temp_file, STATE_FILE)
    os.chmod(STATE_FILE, 0o644)


def state_field(state: dict[str, Any], field: str) -> Any:
    value = state.get(field)
    return "(none)" if value is None else value


def add_transaction(state: dict[str, Any], transaction: dict[str, Any]) -> None:
    transactions = state.setdefault("transactions", [])
    if not isinstance(transactions, list):
        transactions = []
    transactions.append(transaction)
    state["transactions"] = transactions[-20:]
    state["transaction"] = transaction
    save_state(state)


def update_transaction_status(state: dict[str, Any], txn_id: str, status: str, finished_at: str) -> None:
    selected: dict[str, Any] | None = None
    for txn in state.get("transactions", []):
        if isinstance(txn, dict) and txn.get("id") == txn_id:
            txn["status"] = status
            txn["finished_at"] = finished_at
            selected = txn
            break
    if selected is not None:
        state["transaction"] = selected
    if status == "success" and selected:
        state["installed_release"] = selected.get("target_version") or selected.get("manifest_release")
        state["last_successful_upgrade"] = finished_at
        state["available_update"] = None
    save_state(state)


def latest_success_transaction(state: dict[str, Any]) -> dict[str, Any] | None:
    for txn in reversed(state.get("transactions", [])):
        if isinstance(txn, dict) and txn.get("status") == "success":
            return txn
    return None
