"""Expected user-facing OTA failures."""

from .constants import EXIT_ERROR


class OtaError(Exception):
    """Expected user-facing OTA failure with a stable exit code."""

    def __init__(self, message: str, exit_code: int = EXIT_ERROR) -> None:
        super().__init__(message)
        self.exit_code = exit_code
