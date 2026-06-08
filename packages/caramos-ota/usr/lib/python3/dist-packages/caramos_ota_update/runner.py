"""Migration discovery and execution for CaramOS OTA."""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from types import ModuleType
from typing import Callable

from caramos_ota.logging_utils import log_error, log_info

from .context import MigrationContext

MigrationCallable = Callable[[MigrationContext], None]


class MigrationRunnerError(RuntimeError):
    """Raised when migration discovery or execution fails safely."""


@dataclass(frozen=True)
class Migration:
    """One adjacent CaramOS version migration."""

    from_version: str
    to_version: str
    description: str
    run: MigrationCallable
    module_name: str

    @property
    def name(self) -> str:
        """Return a stable migration name for logs/state."""

        return f"{self.from_version}_to_{self.to_version}".replace(".", "_")


class MigrationRunner:
    """Load and run CaramOS OTA migrations."""

    def __init__(self, *, context: MigrationContext, package_name: str = "caramos_ota_update.migrations") -> None:
        self.context = context
        self.package_name = package_name

    def discover(self) -> list[Migration]:
        """Discover migration modules from the migrations package recursively."""

        package = importlib.import_module(self.package_name)
        migrations: list[Migration] = []
        for module_info in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            if module_info.ispkg:
                continue
            module = importlib.import_module(module_info.name)
            migrations.append(self._migration_from_module(module))
        self._validate_migrations(migrations)
        return sorted(migrations, key=lambda item: (item.from_version, item.to_version))

    def resolve_path(self, current_version: str, target_version: str) -> list[Migration]:
        """Resolve adjacent migrations from current_version to target_version."""

        if current_version == target_version:
            return []
        migrations = self.discover()
        by_from = {migration.from_version: migration for migration in migrations}
        path: list[Migration] = []
        seen: set[str] = set()
        cursor = current_version
        while cursor != target_version:
            if cursor in seen:
                raise MigrationRunnerError(f"migration cycle detected at version {cursor}")
            seen.add(cursor)
            migration = by_from.get(cursor)
            if migration is None:
                raise MigrationRunnerError(
                    f"missing migration path from {current_version} to {target_version}; "
                    f"no migration starts at {cursor}"
                )
            path.append(migration)
            cursor = migration.to_version
        return path

    def run(self, *, current_version: str, target_version: str) -> None:
        """Run migrations from current_version to target_version."""

        path = self.resolve_path(current_version, target_version)
        if not path:
            self.context.log(f"CaramOS is already at target version {target_version}")
            return
        self.context.log("Migration path:")
        for migration in path:
            self.context.log(f"- {migration.from_version} -> {migration.to_version}: {migration.description}")
        if self.context.dry_run:
            self.context.log("dry-run complete; no system changes were made")
            return
        for migration in path:
            self._run_one(migration)

    def _run_one(self, migration: Migration) -> None:
        log_info(f"Starting migration {migration.name}: {migration.description}")
        try:
            migration.run(self.context)
            self.context.update_release_file(migration.to_version)
            log_info(f"Finished migration {migration.name}")
        except Exception as exc:
            log_error(f"Migration {migration.name} failed: {exc}")
            raise MigrationRunnerError(f"migration {migration.name} failed: {exc}") from exc

    def _migration_from_module(self, module: ModuleType) -> Migration:
        missing = [
            name
            for name in ("FROM_VERSION", "TO_VERSION", "DESCRIPTION", "run")
            if not hasattr(module, name)
        ]
        if missing:
            raise MigrationRunnerError(f"migration module {module.__name__} missing: {', '.join(missing)}")
        run = getattr(module, "run")
        if not callable(run):
            raise MigrationRunnerError(f"migration module {module.__name__} run is not callable")
        return Migration(
            from_version=str(getattr(module, "FROM_VERSION")),
            to_version=str(getattr(module, "TO_VERSION")),
            description=str(getattr(module, "DESCRIPTION")),
            run=run,
            module_name=module.__name__,
        )

    def _validate_migrations(self, migrations: list[Migration]) -> None:
        seen_from: dict[str, Migration] = {}
        seen_edges: set[tuple[str, str]] = set()
        for migration in migrations:
            if not migration.from_version or not migration.to_version:
                raise MigrationRunnerError(f"migration {migration.module_name} has empty version")
            if migration.from_version == migration.to_version:
                raise MigrationRunnerError(f"migration {migration.module_name} has identical from/to version")
            if migration.from_version in seen_from:
                previous = seen_from[migration.from_version]
                raise MigrationRunnerError(
                    f"duplicate migration start {migration.from_version}: "
                    f"{previous.module_name} and {migration.module_name}"
                )
            seen_from[migration.from_version] = migration
            edge = (migration.from_version, migration.to_version)
            if edge in seen_edges:
                raise MigrationRunnerError(f"duplicate migration edge {migration.from_version} -> {migration.to_version}")
            seen_edges.add(edge)
