"""Migration discovery and execution for CaramOS OTA."""

from __future__ import annotations

import importlib.util
from types import ModuleType

from caramos_ota.logging_utils import log_error, log_info

from .context import MigrationContext
from .ledger import applied_ids, bootstrap_ledger, mark_applied
from .registry import (
    MigrationDescriptor,
    MigrationPlan,
    MigrationRegistryError,
    discover_migrations,
    resolve_plan,
    version_lt,
)
from .state import (
    mark_migration_complete,
    mark_migration_running,
    mark_transaction_failed,
    mark_transaction_success,
    start_transaction,
)


class MigrationRunnerError(RuntimeError):
    """Raised when migration discovery or execution fails safely."""


class MigrationRunner:
    """Load and run legacy plus timestamp CaramOS migrations."""

    def __init__(self, *, context: MigrationContext) -> None:
        self.context = context

    def discover(self) -> list[MigrationDescriptor]:
        try:
            return discover_migrations()
        except MigrationRegistryError as exc:
            raise MigrationRunnerError(str(exc)) from exc

    def resolve_path(self, current_version: str, target_version: str) -> MigrationPlan:
        """Resolve pending migrations from current state to target."""

        descriptors = self.discover()
        try:
            ledger = bootstrap_ledger(
                current_version,
                descriptors,
                persist=not self.context.dry_run,
            )
            return resolve_plan(
                current_version,
                applied_ids=applied_ids(ledger),
                target_version=target_version,
                descriptors=descriptors,
            )
        except Exception as exc:
            raise MigrationRunnerError(str(exc)) from exc

    def run(self, *, current_version: str, target_version: str) -> None:
        """Run all pending migrations through target."""

        descriptors = self.discover()
        try:
            ledger = bootstrap_ledger(
                current_version,
                descriptors,
                persist=not self.context.dry_run,
            )
            plan = resolve_plan(
                current_version,
                applied_ids=applied_ids(ledger),
                target_version=target_version,
                descriptors=descriptors,
            )
        except Exception as exc:
            raise MigrationRunnerError(str(exc)) from exc

        needs_release_finalization = version_lt(current_version, plan.target_version)
        if not plan.migrations and not needs_release_finalization:
            self.context.log(f"CaramOS has no pending migrations through {plan.target_version}")
            return

        if plan.migrations:
            self.context.log("Migration plan:")
            for migration in plan.migrations:
                self.context.log(
                    f"- {migration.migration_id}: {migration.description}"
                )
        else:
            self.context.log(
                f"No pending migrations; finalizing release metadata for {plan.target_version}"
            )
        if self.context.dry_run:
            if needs_release_finalization:
                self.context.update_release_file(plan.target_version)
            self.context.log("dry-run complete; no system changes were made")
            return

        transaction_id = start_transaction(
            target_version=plan.target_version,
            migration_ids=[item.migration_id for item in plan.migrations],
        )
        cursor = current_version
        for migration in plan.migrations:
            mark_migration_running(transaction_id=transaction_id, migration_id=migration.migration_id)
            try:
                self._run_one(migration)
                if migration.legacy and migration.release is not None:
                    self.context.update_release_file(migration.release)
                    cursor = migration.release
                mark_applied(ledger, migration)
                mark_migration_complete(transaction_id=transaction_id, migration_id=migration.migration_id)
            except Exception as exc:
                mark_transaction_failed(
                    transaction_id=transaction_id,
                    migration_id=migration.migration_id,
                    message=str(exc),
                )
                raise

        if version_lt(cursor, plan.target_version):
            self.context.update_release_file(plan.target_version)
        mark_transaction_success(transaction_id=transaction_id, installed_version=plan.target_version)

    def _run_one(self, migration: MigrationDescriptor) -> None:
        log_info(f"Starting migration {migration.migration_id}: {migration.description}")
        try:
            module = self._load_module(migration)
            self._validate_module(module, migration)
            getattr(module, "run")(self.context)
            log_info(f"Finished migration {migration.migration_id}")
        except MigrationRunnerError:
            raise
        except Exception as exc:
            log_error(f"Migration {migration.migration_id} failed: {exc}")
            raise MigrationRunnerError(f"migration {migration.migration_id} failed: {exc}") from exc

    def _load_module(self, migration: MigrationDescriptor) -> ModuleType:
        module_name = f"caramos_ota_migration_{migration.migration_id}"
        spec = importlib.util.spec_from_file_location(module_name, migration.module_path)
        if spec is None or spec.loader is None:
            raise MigrationRunnerError(f"cannot load migration module: {migration.module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _validate_module(self, module: ModuleType, migration: MigrationDescriptor) -> None:
        missing = [name for name in ("DESCRIPTION", "run") if not hasattr(module, name)]
        if missing:
            raise MigrationRunnerError(
                f"migration {migration.migration_id} module missing: {', '.join(missing)}"
            )
        if not callable(getattr(module, "run")):
            raise MigrationRunnerError(f"migration {migration.migration_id} run is not callable")
        if migration.legacy:
            for attribute, expected in (
                ("FROM_VERSION", migration.from_version),
                ("TO_VERSION", migration.to_version),
            ):
                actual = str(getattr(module, attribute, ""))
                if actual != expected:
                    raise MigrationRunnerError(
                        f"migration {migration.migration_id} {attribute} mismatch: {actual!r} vs {expected!r}"
                    )
