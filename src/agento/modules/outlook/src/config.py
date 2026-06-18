from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OutlookConfig:
    """Python-side Outlook config — NO Graph secrets.

    The Graph credentials (``outlook_tenant_id``, ``outlook_client_id``, ``outlook_client_secret``,
    ``outlook_cert_pem``/``outlook_cert_password``) and the mailbox UPN (``outlook_mailbox_user_id``) live in ``system.json``
    and are resolved by the TOOLBOX (the zero-trust boundary — "toolbox = only container with
    secrets"). They are deliberately NOT fields here, exactly as ``JiraConfig`` omits ``jira_token``
    despite the ``obscure`` schema. Bootstrap stores this dataclass in ``_MODULE_CONFIGS``, so keeping
    the secret out of it means the cron/framework registry never holds the Graph secret.
    """

    enabled: bool = False
    poll_top: int = 10
    allowed_senders: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> OutlookConfig:
        # 3-level config (ENV/DB) returns STRINGS, so bool("0")/bool("false") would be True.
        # Mirror JiraConfig.from_dict's truthiness set.
        enabled_raw = data.get("enabled", False)
        enabled = enabled_raw not in (False, 0, "0", "false", "False")
        # poll_top arrives as str/int/garbage — parse defensively and clamp to Graph's 1..50 contract.
        # A missing/None value falls back to 10; an explicit 0 (or negative) clamps to 1.
        poll_top_raw = data.get("poll_top", 10)
        if poll_top_raw is None:
            poll_top_raw = 10
        try:
            poll_top = int(poll_top_raw)
        except (TypeError, ValueError):
            poll_top = 10
        poll_top = min(max(poll_top, 1), 50)
        allowed_senders = data.get("allowed_senders", "") or ""
        # NOTE: tenant/client/secret/cert/mailbox keys in `data` are intentionally ignored here — they
        # are the toolbox's concern. Do not add them as fields.
        return cls(
            enabled=enabled,
            poll_top=poll_top,
            allowed_senders=allowed_senders,
        )

    @property
    def allowed_senders_list(self) -> list[str]:
        return [s.strip().lower() for s in self.allowed_senders.split(",") if s.strip()]

    @property
    def toolbox_url(self) -> str:
        from agento.framework.bootstrap import get_module_config

        core_cfg = get_module_config("core")
        if isinstance(core_cfg, dict):
            return core_cfg.get("toolbox/url", "") or ""
        return ""
