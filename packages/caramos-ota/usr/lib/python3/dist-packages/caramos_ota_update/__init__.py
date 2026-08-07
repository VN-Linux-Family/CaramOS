"""CaramOS OTA version migration runner package."""

from .registry import MigrationDescriptor, MigrationPlan
from .runner import MigrationRunner, MigrationRunnerError

__all__ = ["MigrationDescriptor", "MigrationPlan", "MigrationRunner", "MigrationRunnerError"]
