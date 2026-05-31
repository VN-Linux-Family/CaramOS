"""CaramOS repository verification."""

from __future__ import annotations

import os
from pathlib import Path

from .constants import EXIT_REPO, KEYRING_FILE, PPA_PATTERN
from .logging_utils import log_error, log_info, print_ok


def verify_repo() -> None:
    """Verify that the CaramOS keyring and PPA source are present."""

    if not KEYRING_FILE.is_file() or not os.access(KEYRING_FILE, os.R_OK):
        print("Error: CaramOS keyring not found.")
        print(f"Missing: {KEYRING_FILE}")
        print("\nThe keyring should be pre-installed in the CaramOS ISO.")
        log_error(f"Keyring not found: {KEYRING_FILE}")
        raise SystemExit(EXIT_REPO)

    sources: list[Path] = []
    sources_dir = Path("/etc/apt/sources.list.d")
    if sources_dir.is_dir():
        sources.extend(p for p in sources_dir.iterdir() if p.is_file())
    main_sources = Path("/etc/apt/sources.list")
    if main_sources.is_file():
        sources.append(main_sources)

    found = False
    for source in sources:
        try:
            if PPA_PATTERN in source.read_text(encoding="utf-8", errors="ignore"):
                found = True
                break
        except OSError:
            continue

    if not found:
        print("Error: CaramOS repository not found.")
        print("The CaramOS PPA should be pre-configured in /etc/apt/sources.list.d/.")
        print("\nExpected repository:")
        print(f"  deb [signed-by={KEYRING_FILE}] https://{PPA_PATTERN}/ubuntu/ noble main")
        log_error("CaramOS PPA not found in APT sources")
        raise SystemExit(EXIT_REPO)

    print_ok("Repository: ppa:vietnamlinuxfamily/caram-os")
    log_info("Repository verified")
