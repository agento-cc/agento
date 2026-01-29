# Encryption

Fields marked as `"type": "obscure"` in module.json are encrypted when stored in `core_config_data`.

## Setup

The encryption key is generated automatically during `bin/agento install`:

```env
# In secrets.env
AGENTO_ENCRYPTION_KEY=<64-char hex string>
```

If you need to set it manually:
```bash
echo "AGENTO_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> ../secrets.env
```

## How It Works

1. `bin/agento config:set my_app/tools/mysql_prod/pass secret` — Python checks if `pass` field is `obscure` in module.json
2. If yes → encrypts with AES-256-CBC → stores as `aes256:{iv_hex}:{ciphertext_hex}` with `encrypted=1`
3. Toolbox reads DB at runtime → decrypts using the same `AGENTO_ENCRYPTION_KEY`

## Algorithm

- **Cipher:** AES-256-CBC
- **Key derivation:** SHA-256 of `AGENTO_ENCRYPTION_KEY`
- **IV:** Random 16 bytes per encryption
- **Padding:** PKCS7
- **Format in DB:** `aes256:{iv_hex}:{ciphertext_hex}`

## Cross-Language Compatibility

Both Python and Node.js implementations produce/consume the same format:

| Language | File | Used By |
|----------|------|---------|
| Python | [src/agento/framework/crypto.py](../../src/agento/framework/crypto.py) | `config:set` (encrypt) |
| Node.js | [docker/toolbox/crypto.js](../../docker/toolbox/crypto.js) | Config loader (decrypt) |

## Which Fields Are Encrypted

Any field with `"type": "obscure"` in module.json:

```json
{
  "fields": {
    "pass": {"type": "obscure", "label": "Password"},
    "host": {"type": "string", "label": "Host"}
  }
}
```

Only `pass` would be encrypted. `host` is stored as plain text.

## Key Rotation

Currently manual: re-encrypt all values with a new key by reading + re-setting each obscure config value after changing `AGENTO_ENCRYPTION_KEY`.
