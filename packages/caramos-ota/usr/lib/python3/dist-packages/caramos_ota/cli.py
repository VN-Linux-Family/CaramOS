"""Command-line interface for CaramOS OTA."""

from __future__ import annotations

import argparse
import os
import subprocess
from typing import Any

from .apt import (
    apt_update,
    detect_updates,
    downgrade_package,
    install_packages,
    installed_version,
    print_repair_result,
    remove_package,
    repair_apt,
    repair_dpkg,
)
from .constants import EXIT_APT, EXIT_CANCEL, EXIT_ERROR, EXIT_OK, TOOL_NAME, TOOL_VERSION
from .logging_utils import current_log_file, init_log, log_error, log_info, now_iso
from .manifest import validate_package_name
from .models import Manifest, ReleaseInfo, UpdatePackage
from .privilege import acquire_lock, require_root
from .release import detect_caramos
from .repo import verify_repo
from .state import (
    latest_success_transaction,
    load_state,
    save_state,
    state_field,
    update_transaction_status,
)


def banner() -> None:
    """Print the CLI banner."""

    title = f"CaramOS OTA Updater v{TOOL_VERSION}"
    border = "═" * (len(title) + 8)
    print(f"╔{border}╗")
    print(f"║    {title}    ║")
    print(f"╚{border}╝")
    print()


def show_updates(updates: list[UpdatePackage]) -> None:
    """Print the migration update summary table."""

    if not updates:
        print("No CaramOS migration updates are available.")
        return
    print("Available CaramOS migration update:\n")
    print(f"  {'Item':35} {'Current':12} Target")
    print("  ─────────────────────────────────────────────────────")
    for update in updates:
        print(f"  {update.name:35} {update.current_version:12} {update.available_version}")
    print(f"\nTarget release: {updates[0].available_version}")


def self_update_ota_if_needed(*, skip_self_update: bool, reexec_args: list[str]) -> None:
    """Upgrade caramos-ota first and re-exec into the new code when changed."""

    if skip_self_update:
        log_info("Skipping OTA self-update because --skip-self-update is set")
        return

    before = installed_version("caramos-ota")
    print("Updating CaramOS OTA engine first...")
    log_info(f"OTA self-update before version: {before or '(not installed)'}")
    if not install_packages(["caramos-ota"]):
        log_error("OTA self-update failed")
        print("Error: Failed to update caramos-ota before checking/running migrations.")
        print(f"Log: {current_log_file()}")
        raise SystemExit(EXIT_APT)

    after = installed_version("caramos-ota")
    log_info(f"OTA self-update after version: {after or '(not installed)'}")
    if before == after:
        print("CaramOS OTA engine is already up to date.")
        return

    print(f"CaramOS OTA engine updated: {before or '(none)'} → {after}")
    print("Restarting updater with the new OTA engine...")
    log_info("Re-execing caramos-ota after self-update: " + " ".join(reexec_args))
    os.execv("/usr/bin/caramos-ota", reexec_args)


def run_migration_update(target_version: str, *, dry_run: bool) -> None:
    """Invoke caramos-ota-update for the target CaramOS version."""

    command = ["/usr/bin/caramos-ota-update", "--target", target_version]
    if dry_run:
        command.append("--dry-run")
    log_info("Running updater: " + " ".join(command))
    result = subprocess.run(command, check=False, text=True)
    if result.returncode != 0:
        log_error(f"caramos-ota-update failed with exit code {result.returncode}")
        print("Error: Migration update failed.")
        print(f"Log: {current_log_file()}")
        raise SystemExit(result.returncode)


def do_upgrade(
    manifest: Manifest,
    updates: list[UpdatePackage],
    state: dict[str, Any],
    auto_yes: bool,
    *,
    skip_self_update: bool,
) -> None:
    """Run the migration-driven OTA upgrade."""

    target_version = manifest.release
    print(f"CaramOS target version: {target_version}")
    if updates:
        show_updates(updates)
        print()
    if not auto_yes:
        answer = input(f"Update CaramOS to {target_version}? [Y/n] ")
        if answer.lower().startswith("n"):
            print("Update cancelled.")
            log_info("User cancelled update")
            raise SystemExit(EXIT_CANCEL)

    self_update_ota_if_needed(
        skip_self_update=skip_self_update,
        reexec_args=["caramos-ota", "--upgrade", "--yes", "--skip-self-update"],
    )
    run_migration_update(target_version, dry_run=False)
    state["last_successful_upgrade"] = now_iso()
    state["installed_release"] = target_version
    state["available_update"] = None
    save_state(state)
    print("\nUpdate complete.")
    print(f"CaramOS is now on version {target_version}.")


def do_status(release_info: ReleaseInfo, state: dict[str, Any]) -> None:
    """Print the current OTA status."""

    print("CaramOS OTA Status")
    print("──────────────────")
    print(f"CaramOS version:      {release_info.version}")
    print(f"OTA tool version:     {TOOL_VERSION}")
    print(f"Last check:           {state_field(state, 'last_check')}")
    print(f"Last upgrade:         {state_field(state, 'last_successful_upgrade')}")
    print(f"Installed release:    {state_field(state, 'installed_release')}\n")

    txn = latest_success_transaction(state)
    if not txn:
        print("No successful OTA transactions recorded.")
        return
    print("Latest successful transaction:")
    print(f"  ID:      {txn.get('id', '?')}")
    print(f"  Release: {txn.get('manifest_release', '?')}")
    print(f"  Date:    {txn.get('finished_at', '?')}")
    print("  Migration marker:")
    for package in txn.get("packages", []):
        if not isinstance(package, dict):
            continue
        old = package.get("old_version") or "(previous)"
        print(f"    {package.get('name', '?')}  {old} → {package.get('new_version', '?')}")


def do_repair() -> None:
    """Run best-effort APT/dpkg repair."""

    print("CaramOS OTA Repair")
    print("──────────────────\n")
    log_info("Starting repair")

    print("Running dpkg --configure -a ...")
    print_repair_result(repair_dpkg(), "dpkg configure completed", "dpkg configure had errors")

    print("\nRunning apt-get --fix-broken install ...")
    print_repair_result(repair_apt(), "apt fix-broken install completed", "apt fix-broken install had errors")

    print("\nRepair finished. Check log for details:")
    print(f"  {current_log_file()}")


def do_rollback(state: dict[str, Any]) -> None:
    """Rollback the latest successful transaction on a best-effort basis."""

    print("CaramOS OTA Rollback (best-effort)")
    print("───────────────────────────────────\n")
    txn = latest_success_transaction(state)
    if not txn:
        print("No successful OTA transaction found to roll back.")
        return

    txn_id = str(txn.get("id", "?"))
    print(f"Transaction to rollback: {txn_id}\n")
    print("Packages to rollback:")
    packages = [p for p in txn.get("packages", []) if isinstance(p, dict)]
    for package in packages:
        old = package.get("old_version")
        new = package.get("new_version", "?")
        if package.get("action") == "install" or not old:
            print(f"  {package.get('name', '?')}  {new} → remove")
        else:
            print(f"  {package.get('name', '?')}  {new} → {old}")

    answer = input("\nRollback these changes? [Y/n] ")
    if answer.lower().startswith("n"):
        print("Rollback cancelled.")
        log_info("User cancelled rollback")
        raise SystemExit(EXIT_CANCEL)

    log_info(f"Starting rollback of transaction {txn_id}")
    for package in reversed(packages):
        name = str(package.get("name", ""))
        if not validate_package_name(name):
            log_error(f"Rollback skipped invalid package name: {name}")
            continue
        old_version = package.get("old_version")
        if package.get("action") == "install" or not old_version:
            print(f"Removing: {name}")
            if remove_package(name):
                print(f"[✓] Removed {name}")
            else:
                print(f"[✗] Failed to remove {name}")
        else:
            print(f"Downgrading: {name} to {old_version}")
            if downgrade_package(name, str(old_version)):
                print(f"[✓] Downgraded {name} to {old_version}")
            else:
                print(f"[✗] Failed to downgrade {name} to {old_version}")
    update_transaction_status(state, txn_id, "rolled_back", now_iso())
    log_info(f"Rollback of transaction {txn_id} completed")
    print("\nRollback finished.")
    print("Note: Rollback is best-effort. Some changes may not be fully reversible.")
    print(f"Check log: {current_log_file()}")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=f"CaramOS OTA Updater v{TOOL_VERSION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  sudo caramos-ota               Check and install updates
  sudo caramos-ota --check       Check only
  sudo caramos-ota --yes         Install without asking
  sudo caramos-ota --dry-run     Preview changes
  sudo caramos-ota --status      Show OTA status
  sudo caramos-ota --repair      Fix broken packages
  sudo caramos-ota --rollback    Rollback last update

Exit codes:
  0  Success / no updates available
  1  General error
  2  Root privileges required
  3  Not running on CaramOS
  4  Repository/keyring error
  5  APT/dpkg error
  6  Manifest/state error
  7  Another operation is running
  8  User cancelled""",
    )
    parser.add_argument("--check", action="store_true", help="Check for updates only (do not install)")
    parser.add_argument("--upgrade", action="store_true", help="Explicitly upgrade (same as default)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip interactive confirmation")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be installed without installing")
    parser.add_argument("--status", action="store_true", help="Show current CaramOS OTA status")
    parser.add_argument("--repair", action="store_true", help="Fix broken package state")
    parser.add_argument("--rollback", action="store_true", help="Rollback the latest successful OTA transaction")
    parser.add_argument(
        "--skip-self-update",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--version", "-V", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    return parser


def selected_action(args: argparse.Namespace) -> str:
    """Return the single requested action or the default action."""

    actions = [
        name
        for name in ("check", "upgrade", "status", "repair", "rollback")
        if getattr(args, name)
    ]
    if len(actions) > 1:
        print("Error: Please choose only one action.")
        raise SystemExit(EXIT_ERROR)
    return actions[0] if actions else "default"


def main(argv: list[str] | None = None) -> int:
    """Run the CaramOS OTA CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    action = selected_action(args)

    require_root()
    init_log()
    log_info(f"Starting {TOOL_NAME} {TOOL_VERSION} action={action}")
    acquire_lock()
    state = load_state()
    release_info = detect_caramos()

    if action == "status":
        do_status(release_info, state)
    elif action == "repair":
        do_repair()
    elif action == "rollback":
        do_rollback(state)
    elif action == "check":
        banner()
        verify_repo()
        apt_update()
        self_update_ota_if_needed(
            skip_self_update=args.skip_self_update,
            reexec_args=["caramos-ota", "--check", "--skip-self-update"],
        )
        state["last_check"] = now_iso()
        save_state(state)
        _, updates = detect_updates(release_info, state)
        print()
        if updates:
            print(f"{len(updates)} update(s) available. Run 'sudo {TOOL_NAME}' to install.")
        else:
            print("No CaramOS OTA updates are available.")
    else:
        banner()
        verify_repo()
        apt_update()
        state["last_check"] = now_iso()
        save_state(state)
        manifest, updates = detect_updates(release_info, state)
        print()
        if args.dry_run:
            show_updates(updates)
            print(f"\n(dry-run: would run /usr/bin/caramos-ota-update --target {manifest.release} --dry-run)")
            run_migration_update(manifest.release, dry_run=True)
        else:
            do_upgrade(manifest, updates, state, args.yes, skip_self_update=args.skip_self_update)

    log_info(f"Finished {TOOL_NAME} action={action}")
    return EXIT_OK
