from unittest.mock import MagicMock

from agento.modules.outlook.src.onboarding import OutlookOnboarding


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
        "outlook/outlook_cert_path",
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
