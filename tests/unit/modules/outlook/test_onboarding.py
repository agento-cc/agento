import logging
from unittest.mock import MagicMock

from agento.modules.outlook.src.onboarding import (
    OutlookOnboarding,
    _pem_has_cert_and_key,
    _read_pem_block,
)

_VALID_PEM_LINES = [
    "-----BEGIN CERTIFICATE-----",
    "MIIBcert",
    "-----END CERTIFICATE-----",
    "-----BEGIN PRIVATE KEY-----",
    "MIIEkey",
    "-----END PRIVATE KEY-----",
]


def _conn_with_paths(paths):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [{"path": p} for p in paths]
    return conn


def test_describe_is_human_readable():
    assert "Outlook" in OutlookOnboarding().describe()


def test_is_complete_true_with_client_secret_auth():
    conn = _conn_with_paths([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
        "outlook/outlook_client_secret",
        "outlook/outlook_mailbox_user_id",
    ])
    assert OutlookOnboarding().is_complete(conn) is True


def test_is_complete_true_with_certificate_auth():
    conn = _conn_with_paths([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
        "outlook/outlook_cert_pem",
        "outlook/outlook_mailbox_user_id",
    ])
    assert OutlookOnboarding().is_complete(conn) is True


def test_is_complete_false_when_no_auth_secret_or_cert():
    conn = _conn_with_paths([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
        "outlook/outlook_mailbox_user_id",
    ])
    assert OutlookOnboarding().is_complete(conn) is False


def test_is_complete_false_when_missing_base_keys():
    conn = _conn_with_paths(["outlook/outlook_tenant_id"])
    assert OutlookOnboarding().is_complete(conn) is False


# --- PEM reader / validation helpers -------------------------------------------------------------

def test_read_pem_block_joins_lines_until_END(monkeypatch):
    feed = iter([*_VALID_PEM_LINES, "END", "ignored-after"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(feed))
    pem = _read_pem_block("paste:")
    assert pem == "\n".join(_VALID_PEM_LINES)
    assert "ignored-after" not in pem


def test_read_pem_block_stops_at_EOF(monkeypatch):
    feed = iter(_VALID_PEM_LINES)

    def _input(*a, **k):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError from None

    monkeypatch.setattr("builtins.input", _input)
    assert _read_pem_block("paste:") == "\n".join(_VALID_PEM_LINES)


def test_pem_has_cert_and_key_requires_both_markers():
    assert _pem_has_cert_and_key("\n".join(_VALID_PEM_LINES)) is True
    # cert only
    assert _pem_has_cert_and_key(
        "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----"
    ) is False
    # key only
    assert _pem_has_cert_and_key(
        "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----"
    ) is False
    # RSA / ENCRYPTED private-key variants are accepted by the PRIVATE KEY----- marker
    assert _pem_has_cert_and_key(
        "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n"
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\ny\n-----END ENCRYPTED PRIVATE KEY-----"
    ) is True


# --- run(): branch-switch cleanup + ordering -----------------------------------------------------

def _patch_run(monkeypatch, *, auth_choice, inputs, getpass_value):
    """Patch onboarding's run() dependencies; return (conn, calls).

    `calls` records the ORDER of config writes/deletes and conn.commit so tests can assert that
    stale-credential deletes happen in the same transaction (before commit).
    """
    calls = []
    conn = MagicMock()
    conn.commit.side_effect = lambda: calls.append(("commit",))

    feed = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(feed))
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: getpass_value)
    monkeypatch.setattr("agento.framework.cli.terminal.select", lambda *a, **k: auth_choice)
    monkeypatch.setattr(
        "agento.framework.core_config.config_set",
        lambda conn, path, value, **k: calls.append(("set", path, value)),
    )
    monkeypatch.setattr(
        "agento.framework.core_config.config_set_auto_encrypt",
        lambda conn, path, value, **k: calls.append(("set_enc", path, value)),
    )
    monkeypatch.setattr(
        "agento.framework.core_config.config_delete",
        lambda conn, path, **k: calls.append(("del", path)),
    )
    # No toolbox URL -> run() commits then short-circuits the Graph verification.
    monkeypatch.setattr("agento.framework.bootstrap.get_module_config", lambda m: {})
    return conn, calls


def _deleted(calls):
    return [c[1] for c in calls if c[0] == "del"]


def _assert_all_writes_before_commit(calls):
    commit_idx = next(i for i, c in enumerate(calls) if c[0] == "commit")
    write_idxs = [i for i, c in enumerate(calls) if c[0] in ("set", "set_enc", "del")]
    assert write_idxs, "expected config writes before commit"
    assert all(i < commit_idx for i in write_idxs)


def test_run_secret_branch_clears_stale_cert_material_before_commit(monkeypatch):
    conn, calls = _patch_run(
        monkeypatch,
        auth_choice=0,
        inputs=["tid", "cid", "agent@example.com"],
        getpass_value="the-secret",
    )
    OutlookOnboarding().run(conn, {}, logging.getLogger("t"))

    assert ("set_enc", "outlook/outlook_client_secret", "the-secret") in calls
    deleted = _deleted(calls)
    assert "outlook/outlook_cert_pem" in deleted
    assert "outlook/outlook_cert_password" in deleted
    assert "outlook/outlook_cert_path" in deleted  # legacy
    _assert_all_writes_before_commit(calls)


def test_run_cert_branch_stores_pem_clears_secret_and_blank_passphrase(monkeypatch):
    conn, calls = _patch_run(
        monkeypatch,
        auth_choice=1,
        inputs=["tid", "cid", "agent@example.com", *_VALID_PEM_LINES, "END"],
        getpass_value="",  # blank passphrase
    )
    OutlookOnboarding().run(conn, {}, logging.getLogger("t"))

    assert ("set_enc", "outlook/outlook_cert_pem", "\n".join(_VALID_PEM_LINES)) in calls
    # blank passphrase -> cert_password is NOT stored, and any stale one is deleted
    assert not any(c[0] == "set_enc" and c[1] == "outlook/outlook_cert_password" for c in calls)
    deleted = _deleted(calls)
    assert "outlook/outlook_cert_password" in deleted
    assert "outlook/outlook_client_secret" in deleted
    assert "outlook/outlook_cert_path" in deleted  # legacy
    _assert_all_writes_before_commit(calls)


def test_run_cert_branch_keeps_passphrase_unstripped(monkeypatch):
    conn, calls = _patch_run(
        monkeypatch,
        auth_choice=1,
        inputs=["tid", "cid", "agent@example.com", *_VALID_PEM_LINES, "END"],
        getpass_value="  spaced-pass  ",  # must NOT be stripped
    )
    OutlookOnboarding().run(conn, {}, logging.getLogger("t"))

    assert ("set_enc", "outlook/outlook_cert_password", "  spaced-pass  ") in calls
    # cert_password is stored, not deleted
    assert "outlook/outlook_cert_password" not in _deleted(calls)


def test_run_cert_branch_reprompts_until_pem_has_both_markers(monkeypatch):
    cert_only = ["-----BEGIN CERTIFICATE-----", "x", "-----END CERTIFICATE-----"]
    conn, calls = _patch_run(
        monkeypatch,
        auth_choice=1,
        inputs=["tid", "cid", "agent@example.com", *cert_only, "END", *_VALID_PEM_LINES, "END"],
        getpass_value="",
    )
    OutlookOnboarding().run(conn, {}, logging.getLogger("t"))
    # The cert-only paste is rejected; the second (valid) paste is what gets stored.
    assert ("set_enc", "outlook/outlook_cert_pem", "\n".join(_VALID_PEM_LINES)) in calls
