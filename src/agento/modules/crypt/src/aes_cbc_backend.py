"""AES-256-CBC encryption backend — wraps crypto.py into the Encryptor protocol."""

from agento.framework.crypto import decrypt, encrypt


class AesCbcBackend:
    """In-DB AES-256-CBC encryption. Default backend."""

    def encrypt(self, plaintext: str) -> str:
        return encrypt(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        return decrypt(ciphertext)
