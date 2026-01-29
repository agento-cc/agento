"""Encryptor protocol and accessor — adapter pattern for secret encryption.

Modules register a backend via set_encryptor(). Callers use get_encryptor()
to encrypt/decrypt without knowing the implementation. Falls back to
crypto.py (AES-256-CBC) if no backend is registered.
"""
from __future__ import annotations

from typing import Protocol


class Encryptor(Protocol):
    """Interface for encryption backends."""

    def encrypt(self, plaintext: str) -> str: ...
    def decrypt(self, ciphertext: str) -> str: ...


class _FallbackEncryptor:
    """Default backend — delegates to crypto.py (AES-256-CBC)."""

    def encrypt(self, plaintext: str) -> str:
        from .crypto import encrypt
        return encrypt(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        from .crypto import decrypt
        return decrypt(ciphertext)


_instance: Encryptor | None = None


def get_encryptor() -> Encryptor:
    """Return the registered encryption backend, or fallback to AES-256-CBC."""
    if _instance is None:
        return _FallbackEncryptor()
    return _instance


def set_encryptor(enc: Encryptor) -> None:
    """Register an encryption backend (called by crypt module observer)."""
    global _instance
    _instance = enc
