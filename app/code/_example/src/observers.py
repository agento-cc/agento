"""Example observers — demonstrates event-observer pattern.

Copy this file into your module's src/ directory and customize.
Register observers in your module's events.json.
"""

import logging

logger = logging.getLogger(__name__)


class JobFailedObserver:
    """Called on every job failure (before retry/dead decision)."""

    def execute(self, event):
        logger.warning(
            "Job %d failed: %s", event.job.id, event.error,
        )


class JobSucceededObserver:
    """Called after a job completes successfully."""

    def execute(self, event):
        logger.info(
            "Job %d succeeded in %dms", event.job.id, event.elapsed_ms,
        )


class ModuleRegisterObserver:
    """Called when this module is first loaded."""

    def execute(self, event):
        logger.info("Module %s: registering", event.name)


class ModuleReadyObserver:
    """Called after all modules are loaded."""

    def execute(self, event):
        logger.info("Module %s: ready", event.name)


class ModuleShutdownObserver:
    """Called during graceful shutdown."""

    def execute(self, event):
        logger.info("Module %s: shutting down", event.name)


class ConfigSavedObserver:
    """Called after a config value is set via CLI."""

    def execute(self, event):
        logger.info("Config saved: %s (encrypted=%s)", event.path, event.encrypted)


class SetupCompleteObserver:
    """Called after setup:upgrade finishes."""

    def execute(self, event):
        logger.info("Setup complete (dry_run=%s)", event.dry_run)
