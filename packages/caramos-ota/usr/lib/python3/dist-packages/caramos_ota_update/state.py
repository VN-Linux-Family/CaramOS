"""State helpers for the CaramOS OTA migration runner."""

from __future__ import annotations

from typing import Any

from caramos_ota.logging_utils import current_log_file, now_iso
from caramos_ota.state import load_state, save_state


def mark_transaction_running(*, target_version: str, migration_name: str) -> None:
    """Record the migration currently running."""

    state = load_state()
    state["transaction"] = {
        "status": "running",
        "target_version": target_version,
        "current_migration": migration_name,
        "started_at": now_iso(),
        "log": str(current_log_file() or ""),
    }
    save_state(state)


def mark_transaction_success(*, installed_version: str, target_version: str) -> None:
    """Record a successful migration transaction."""

    state = load_state()
    state["installed_version"] = installed_version
    state["transaction"] = {
        "status": "success",
        "target_version": target_version,
        "finished_at": now_iso(),
        "log": str(current_log_file() or ""),
    }
    state["available_update"] = None
    save_state(state)


def mark_transaction_failed(*, target_version: str, migration_name: str, message: str) -> None:
    """Record a failed migration transaction."""

    state = load_state()
    transaction: dict[str, Any] = {
        "status": "failed",
        "target_version": target_version,
        "current_migration": migration_name,
        "failed_at": now_iso(),
        "message": message,
        "log": str(current_log_file() or ""),
    }
    state["transaction"] = transaction
    save_state(state)
