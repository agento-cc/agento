from dataclasses import fields

from agento.modules.bitbucket.src.config import BitbucketConfig


def test_from_dict_coerces_stringy_enabled():
    assert BitbucketConfig.from_dict({"enabled": "0"}).enabled is False
    assert BitbucketConfig.from_dict({"enabled": "false"}).enabled is False
    assert BitbucketConfig.from_dict({"enabled": False}).enabled is False
    assert BitbucketConfig.from_dict({"enabled": "1"}).enabled is True
    assert BitbucketConfig.from_dict({"enabled": True}).enabled is True
    # An unset field resolved via per-path .get() arrives as None — must be treated as disabled.
    assert BitbucketConfig.from_dict({"enabled": None}).enabled is False


def test_from_dict_clamps_poll_top():
    assert BitbucketConfig.from_dict({"poll_top": "500"}).poll_top == 50
    assert BitbucketConfig.from_dict({"poll_top": "0"}).poll_top == 1
    assert BitbucketConfig.from_dict({"poll_top": None}).poll_top == 20
    assert BitbucketConfig.from_dict({"poll_top": "garbage"}).poll_top == 20
    assert BitbucketConfig.from_dict({"poll_top": 7}).poll_top == 7


def test_repo_list_splits_trims_and_dedupes_preserving_order():
    cfg = BitbucketConfig.from_dict({"repo_allowlist": " api , web ,api, , web "})
    assert cfg.repo_list == ["api", "web"]


def test_empty_repo_allowlist_yields_empty_list():
    assert BitbucketConfig.from_dict({"repo_allowlist": ""}).repo_list == []
    assert BitbucketConfig.from_dict({}).repo_list == []


def test_workspace_and_account_uuid_resolved():
    cfg = BitbucketConfig.from_dict(
        {"bitbucket_workspace": "acme", "bitbucket_account_uuid": "{uuid-1}"}
    )
    assert cfg.workspace == "acme"
    assert cfg.account_uuid == "{uuid-1}"


def test_api_token_is_not_a_field_toolbox_only():
    # The token must never be modeled Python-side (mirrors OutlookConfig omitting Graph secrets).
    field_names = {f.name for f in fields(BitbucketConfig)}
    assert "bitbucket_api_token" not in field_names
    assert "api_token" not in field_names
    # Even if a resolved dict carries it (it never should), from_dict must ignore it.
    cfg = BitbucketConfig.from_dict({"bitbucket_api_token": "secret-token"})
    assert not hasattr(cfg, "bitbucket_api_token")
