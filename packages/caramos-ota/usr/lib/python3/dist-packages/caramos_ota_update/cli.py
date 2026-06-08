"""CLI for the CaramOS OTA migration runner."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from caramos_ota.constants import EXIT_ERROR, EXIT_OK
from caramos_ota.logging_utils import init_log, log_error, log_info
from caramos_ota.release import detect_caramos, parse_key_value_file

from .context import MigrationContext
from .runner import MigrationRunner, MigrationRunnerError


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for caramos-ota-update."""

    parser = argparse.ArgumentParser(
        prog="caramos-ota-update",
        description="Run CaramOS version migrations in order.",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Target CaramOS version to migrate to, for example 1.0.4.",
    )
    parser.add_argument(
        "--from",
        dest="from_version",
        help="Override current CaramOS version for testing or controlled recovery.",
    )
    parser.add_argument(
        "--to",
        dest="to_version",
        help="Run only until this version. Defaults to --target when omitted.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the migration path and planned actions without modifying the system.",
    )
    return parser


def _read_current_version(override: str | None) -> str:
    """Return the current CaramOS version, honoring an explicit override."""

    if override:
        return override
    release_info = detect_caramos()
    return release_info.version


def _current_release_values() -> dict[str, str]:
    """Best-effort read of /etc/caramos-release for context metadata."""

    release_file = Path("/etc/caramos-release")
    if not release_file.exists():
        return {}
    return parse_key_value_file(release_file)


def main(argv: list[str] | None = None) -> int:
    """Run the migration CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.dry_run:
        init_log()

    try:
        target_version = args.to_version or args.target
        current_version = _read_current_version(args.from_version)
        release_values = _current_release_values()
        context = MigrationContext(
            dry_run=args.dry_run,
            release_values=release_values,
        )
        runner = MigrationRunner(context=context)
        runner.run(current_version=current_version, target_version=target_version)
    except MigrationRunnerError as exc:
        log_error(str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive CLI boundary.
        log_error(f"Unexpected migration runner failure: {exc}")
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    log_info("Migration runner finished successfully")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
