import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from agento.framework.scoped_config import Scope
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


def _conn_for_is_complete(default_paths, has_mailbox=True):
    """Mock a conn for is_complete: fetchall -> default-scope identity/auth paths; fetchone ->
    whether a mailbox row exists at ANY scope."""
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [{"path": p} for p in default_paths]
    cur.fetchone.return_value = (1,) if has_mailbox else None
    return conn


def test_describe_is_human_readable():
    assert "Outlook" in OutlookOnboarding().describe()


def test_is_complete_true_with_client_secret_auth():
    conn = _conn_for_is_complete([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
        "outlook/outlook_client_secret",
    ], has_mailbox=True)
    assert OutlookOnboarding().is_complete(conn) is True


def test_is_complete_true_with_certificate_auth():
    conn = _conn_for_is_complete([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
        "outlook/outlook_cert_pem",
    ], has_mailbox=True)
    assert OutlookOnboarding().is_complete(conn) is True


def test_is_complete_true_when_mailbox_exists_at_any_scope():
    # identity + auth at default, mailbox present somewhere (default OR agent_view scope).
    conn = _conn_for_is_complete([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
        "outlook/outlook_client_secret",
    ], has_mailbox=True)
    assert OutlookOnboarding().is_complete(conn) is True


def test_is_complete_false_without_any_mailbox():
    conn = _conn_for_is_complete([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
        "outlook/outlook_client_secret",
    ], has_mailbox=False)
    assert OutlookOnboarding().is_complete(conn) is False


def test_is_complete_false_when_no_auth_secret_or_cert():
    conn = _conn_for_is_complete([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
    ], has_mailbox=True)
    assert OutlookOnboarding().is_complete(conn) is False


def test_is_complete_false_when_missing_identity_keys():
    conn = _conn_for_is_complete(["outlook/outlook_tenant_id"], has_mailbox=True)
    assert OutlookOnboarding().is_complete(conn) is False


def test_is_complete_mailbox_query_is_scope_agnostic():
    # The mailbox existence query (the 2nd execute) must NOT be restricted to scope='default'.
    conn = _conn_for_is_complete([
        "outlook/outlook_tenant_id",
        "outlook/outlook_client_id",
        "outlook/outlook_client_secret",
    ], has_mailbox=True)
    cur = conn.cursor.return_value.__enter__.return_value
    OutlookOnboarding().is_complete(conn)
    mailbox_sql = cur.execute.call_args_list[1].args[0]
    assert "outlook_mailbox_user_id" in str(cur.execute.call_args_list[1].args[1])
    assert "scope" not in mailbox_sql.lower()


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
    assert _pem_has_cert_and_key(
        "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----"
    ) is False
    assert _pem_has_cert_and_key(
        "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----"
    ) is False
    assert _pem_has_cert_and_key(
        "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n"
        "-----BEGIN ENCRYPTED PRIVATE KEY-----\ny\n-----END ENCRYPTED PRIVATE KEY-----"
    ) is True


# --- run(): branch-switch cleanup + per-view mailbox + next-steps ---------------------------------

def _patch_run(monkeypatch, *, auth_choice, inputs, getpass_value, views=None, view_choice=0,
               toolbox_url=""):
    """Patch onboarding's run() dependencies; return (conn, calls).

    `calls` records the ORDER of config writes/deletes/selects and conn.commit so tests can assert
    that stale-credential deletes happen in the same transaction (before commit).
    """
    calls = []
    conn = MagicMock()
    conn.commit.side_effect = lambda: calls.append(("commit",))

    feed = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(feed))
    monkeypatch.setattr("getpass.getpass", lambda *a, **k: getpass_value)

    def _select(prompt, options, *a, **k):
        calls.append(("select", prompt))
        if "authentication" in prompt.lower():
            return auth_choice
        return view_choice  # agent_view selection

    monkeypatch.setattr("agento.framework.cli.terminal.select", _select)
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
    monkeypatch.setattr(
        "agento.framework.scoped_config.scoped_config_set",
        lambda conn, path, value, **k: calls.append(
            ("scoped_set", path, value, k.get("scope"), k.get("scope_id"), k.get("encrypted"))
        ),
    )
    if views is None:
        views = [SimpleNamespace(id=1, code="dev")]
    monkeypatch.setattr("agento.framework.workspace.get_active_agent_views", lambda conn: views)
    monkeypatch.setattr(
        "agento.framework.bootstrap.get_module_config",
        lambda m: {"toolbox/url": toolbox_url} if toolbox_url else {},
    )
    client = MagicMock()
    client.list_unread.return_value = {"mailbox": "agent@example.com", "messages": []}
    monkeypatch.setattr(
        "agento.modules.outlook.src.toolbox_client.OutlookToolboxClient",
        lambda *a, **k: client,
    )
    return conn, calls


def _deleted(calls):
    return [c[1] for c in calls if c[0] == "del"]


def _assert_all_writes_before_commit(calls):
    commit_idx = next(i for i, c in enumerate(calls) if c[0] == "commit")
    write_idxs = [i for i, c in enumerate(calls) if c[0] in ("set", "set_enc", "del", "scoped_set")]
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
    assert ("set_enc", "outlook/outlook_cert_pem", "\n".join(_VALID_PEM_LINES)) in calls


def test_single_active_view_saves_mailbox_at_default(monkeypatch):
    conn, calls = _patch_run(
        monkeypatch,
        auth_choice=0,
        inputs=["tid", "cid", "agent@example.com"],
        getpass_value="sec",
        views=[SimpleNamespace(id=1, code="dev")],
    )
    OutlookOnboarding().run(conn, {}, logging.getLogger("t"))

    assert ("set", "outlook/outlook_mailbox_user_id", "agent@example.com") in calls
    assert not any(c[0] == "scoped_set" for c in calls)
    # only the auth-method select runs (no agent_view prompt for a single view)
    selects = [c for c in calls if c[0] == "select"]
    assert len(selects) == 1
    assert "authentication" in selects[0][1].lower()


def test_multi_view_selects_and_saves_mailbox_at_agent_view_scope(monkeypatch):
    conn, calls = _patch_run(
        monkeypatch,
        auth_choice=0,
        inputs=["tid", "cid", "agent@example.com"],
        getpass_value="sec",
        views=[SimpleNamespace(id=10, code="dev"), SimpleNamespace(id=20, code="ops")],
        view_choice=1,  # pick the second view (id=20)
    )
    OutlookOnboarding().run(conn, {}, logging.getLogger("t"))

    scoped = [c for c in calls if c[0] == "scoped_set" and c[1] == "outlook/outlook_mailbox_user_id"]
    assert len(scoped) == 1
    _, _, value, scope, scope_id, encrypted = scoped[0]
    assert value == "agent@example.com"
    assert scope == Scope.AGENT_VIEW
    assert scope_id == 20
    assert encrypted is False
    # mailbox is NOT also written at the default scope
    assert not any(c[0] == "set" and c[1] == "outlook/outlook_mailbox_user_id" for c in calls)
    # two selects: auth method + agent_view choice
    assert len([c for c in calls if c[0] == "select"]) == 2


def test_next_steps_text_has_no_ingress_bind_and_includes_enable(monkeypatch, capsys):
    conn, _ = _patch_run(
        monkeypatch,
        auth_choice=0,
        inputs=["tid", "cid", "agent@example.com"],
        getpass_value="sec",
        toolbox_url="http://toolbox:3001",  # so run() proceeds past verification to next-steps
    )
    OutlookOnboarding().run(conn, {}, logging.getLogger("t"))
    out = capsys.readouterr().out
    assert "tool:enable" in out
    assert "outlook/allowed_senders" in out
    assert "outlook/enabled" in out
    assert "ingress:bind" not in out


def test_next_steps_printed_even_without_toolbox_url(monkeypatch, capsys):
    # toolbox_url default "" -> Graph verification is skipped, but the operator must STILL see the
    # enable guidance (it was previously lost on the early return).
    conn, _ = _patch_run(
        monkeypatch,
        auth_choice=0,
        inputs=["tid", "cid", "agent@example.com"],
        getpass_value="sec",
    )
    OutlookOnboarding().run(conn, {}, logging.getLogger("t"))
    out = capsys.readouterr().out
    assert "core/toolbox/url is not set" in out  # took the no-verify path
    assert "tool:enable" in out
    assert "outlook/enabled" in out
    assert "ingress:bind" not in out
