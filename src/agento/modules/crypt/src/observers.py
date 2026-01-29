"""Observers for the crypt module."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class RegisterEncryptorObserver:
    """Register the AES-256-CBC backend on module load."""

    def execute(self, event) -> None:
        if event.name != "crypt":
            return

        from agento.framework.encryptor import set_encryptor

        from .aes_cbc_backend import AesCbcBackend

        set_encryptor(AesCbcBackend())
        logger.debug("Crypt: registered AesCbcBackend")
