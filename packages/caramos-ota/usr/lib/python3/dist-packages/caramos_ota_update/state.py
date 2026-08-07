"""Transaction state helpers for the CaramOS OTA migration runner."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from caramos_ota.logging_utils import current_log_file, now_iso
from caramos_ota.state import add_transaction, load_state, save_state, update_transaction_status


def start_transaction(*, target_version: str, migration_ids: list[str]) -> str:
    """Create one resumable migration transaction."""

    transaction_id = uuid4().hex
    state = load_state()
    add_transaction(
        state,
        {
            "id": transaction_id,
            "status": "running",
            "target_version": target_version,
            "planned_migrations": migration_ids,
            "completed_migrations": [],
            "current_migration": None,
            "started_at": now_iso(),
            "log": str(current_log_file() or ""),
        },
    )
    return transaction_id


def _selected_transaction(state: dict[str, Any], transaction_id: str) -> dict[str, Any]:
    for transaction in state.get("transactions", []):
        if isinstance(transaction, dict) and transaction.get("id") == transaction_id:
            return transaction
    raise RuntimeError(f"transaction not found: {transaction_id}")


def mark_migration_running(*, transaction_id: str, migration_id: str) -> None:
    state = load_state()
    transaction = _selected_transaction(state, transaction_id)
    transaction["current_migration"] = migration_id
    state["transaction"] = transaction
    save_state(state)


def mark_migration_complete(*, transaction_id: str, migration_id: str) -> None:
    state = load_state()
    transaction = _selected_transaction(state, transaction_id)
    completed = transaction.setdefault("completed_migrations", [])
    if migration_id not in completed:
        completed.append(migration_id)
    transaction["current_migration"] = None
    state["transaction"] = transaction
    save_state(state)


def mark_transaction_success(*, transaction_id: str, installed_version: str) -> None:
    state = load_state()
    transaction = _selected_transaction(state, transaction_id)
    transaction["installed_version"] = installed_version
    update_transaction_status(state, transaction_id, "success", now_iso())


def mark_transaction_failed(*, transaction_id: str, migration_id: str, message: str) -> None:
    state = load_state()
    transaction = _selected_transaction(state, transaction_id)
    transaction["current_migration"] = migration_id
    transaction["message"] = message
    transaction["failed_at"] = now_iso()
    transaction["status"] = "failed"
    state["transaction"] = transaction
    save_state(state)
