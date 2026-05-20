class EncryptObscureRowsAtRest:
    """Re-encrypt rows whose schema declares them obscure but were stored plaintext.

    Background: pre-fix, six config-path parsers used ``len(parts) ∈ {2, 4}``
    dispatch and silently fell through for 3-part paths produced by
    slash-keyed schema fields (e.g. ``agent_view/identity/ssh_private_key``).
    Such rows landed in ``core_config_data`` with ``encrypted = 0`` despite
    ``"type": "obscure"`` in ``system.json``.

    This patch scans the table for ``encrypted = 0`` rows whose path is now
    recognised as obscure and rewrites them encrypted in place. Idempotent.
    """

    def apply(self, conn):
        from agento.framework.core_config import is_path_obscure
        from agento.framework.encryptor import get_encryptor

        encryptor = get_encryptor()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT scope, scope_id, path, value FROM core_config_data "
                "WHERE encrypted = 0"
            )
            rows = cur.fetchall()

        to_fix = []
        for row in rows:
            if isinstance(row, dict):
                scope, scope_id, path, value = (
                    row["scope"], row["scope_id"], row["path"], row["value"],
                )
            else:
                scope, scope_id, path, value = row
            if is_path_obscure(path):
                to_fix.append((scope, scope_id, path, value))

        if not to_fix:
            return

        params = [
            (encryptor.encrypt(value), scope, scope_id, path)
            for scope, scope_id, path, value in to_fix
        ]
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE core_config_data SET value = %s, encrypted = 1 "
                "WHERE scope = %s AND scope_id = %s AND path = %s",
                params,
            )
        conn.commit()

    def require(self):
        # Must run after agent/* -> agent_view/* rename so this patch sees the
        # final path shape when checking is_path_obscure().
        return ["agent_view/RenameAgentConfigPrefix"]
