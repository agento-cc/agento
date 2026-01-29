from __future__ import annotations

import argparse


def main() -> None:
    import contextlib

    from ..bootstrap import bootstrap
    with contextlib.suppress(Exception):
        bootstrap()  # May fail without DB — framework commands still work

    from ..commands import get_commands
    from .compose import cmd_down, cmd_logs, cmd_up
    from .config import cmd_config_get, cmd_config_list, cmd_config_remove, cmd_config_set
    from .dev import cmd_dev_bootstrap
    from .doctor import cmd_doctor
    from .init import cmd_init
    from .module import cmd_make_module, cmd_module_validate
    from .runtime import cmd_consumer, cmd_e2e, cmd_replay, cmd_rotate, cmd_setup_upgrade
    from .token import (
        cmd_token_deregister,
        cmd_token_list,
        cmd_token_refresh,
        cmd_token_register,
        cmd_token_set,
        cmd_token_usage,
    )
    from .toolbox import cmd_toolbox_start

    parser = argparse.ArgumentParser(
        prog="agento",
        description="Agento — AI Agent Framework",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── Standalone commands (no DB required) ──

    sub.add_parser("doctor", help="Check system prerequisites").set_defaults(func=cmd_doctor)

    init_p = sub.add_parser("init", help="Scaffold a new agento project")
    init_p.add_argument("project", help="Project directory name")
    init_p.add_argument("--local", action="store_true", help="Local dev mode (no Docker, external MySQL)")
    init_p.add_argument("--no-example", action="store_true", dest="no_example", help="Skip example module")
    init_p.set_defaults(func=cmd_init)

    sub.add_parser("up", help="Start the agento runtime (Docker Compose)").set_defaults(func=cmd_up)
    sub.add_parser("down", help="Stop the agento runtime").set_defaults(func=cmd_down)

    logs_p = sub.add_parser("logs", help="Show container logs")
    logs_p.add_argument("service", nargs="?", default=None, help="Service name (cron, toolbox, mysql)")
    logs_p.set_defaults(func=cmd_logs)

    # -- Toolbox --
    toolbox_p = sub.add_parser("toolbox", help="Toolbox management")
    toolbox_sub = toolbox_p.add_subparsers(dest="toolbox_command", required=True)
    toolbox_sub.add_parser("start", help="Start the Node.js toolbox locally").set_defaults(func=cmd_toolbox_start)

    # -- Dev --
    dev_p = sub.add_parser("dev", help="Development tools")
    dev_sub = dev_p.add_subparsers(dest="dev_command", required=True)
    dev_sub.add_parser("bootstrap", help="Set up development environment").set_defaults(func=cmd_dev_bootstrap)

    # ── Module-contributed commands (loaded from di.json) ──

    for name, cmd in get_commands().items():
        cmd_p = sub.add_parser(name, help=cmd.help)
        cmd.configure(cmd_p)
        cmd_p.set_defaults(func=cmd.execute)

    # ── Runtime commands (require DB) ──

    con_p = sub.add_parser("consumer", help="Start the job consumer")
    con_p.set_defaults(func=cmd_consumer)

    setup_p = sub.add_parser("setup:upgrade", help="Apply schema migrations, data patches, and install crontab")
    setup_p.add_argument("--dry-run", action="store_true", help="Show pending work without applying")
    setup_p.set_defaults(func=cmd_setup_upgrade)

    # -- Agent Manager: token subcommands --
    token_p = sub.add_parser("token", help="Manage agent tokens")
    token_sub = token_p.add_subparsers(dest="token_command", required=True)

    reg_p = token_sub.add_parser("register", help="Register a new token")
    reg_p.add_argument("agent_type", choices=["claude", "codex"])
    reg_p.add_argument("label")
    reg_p.add_argument("credentials_path", nargs="?", default=None,
                       help="Path to credentials JSON. If omitted, interactive OAuth is launched.")
    reg_p.add_argument("--token-limit", type=int, default=0, dest="token_limit")
    reg_p.add_argument("--model", type=str, default=None, help="Model name (e.g. claude-sonnet-4-20250514, o3)")
    reg_p.set_defaults(func=cmd_token_register)

    ref_p = token_sub.add_parser("refresh", help="Re-authenticate an existing token (interactive OAuth)")
    ref_p.add_argument("token_id", type=int, help="Token ID to refresh")
    ref_p.set_defaults(func=cmd_token_refresh)

    tl_p = token_sub.add_parser("list", help="List registered tokens")
    tl_p.add_argument("--agent-type", choices=["claude", "codex"], dest="agent_type")
    tl_p.add_argument("--all", action="store_true", help="Include disabled tokens")
    tl_p.add_argument("--json", action="store_true")
    tl_p.set_defaults(func=cmd_token_list)

    dereg_p = token_sub.add_parser("deregister", help="Disable a token")
    dereg_p.add_argument("token_id", type=int)
    dereg_p.set_defaults(func=cmd_token_deregister)

    set_p = token_sub.add_parser("set", help="Set a token as primary (sticky, not overridden by rotation)")
    set_p.add_argument("agent_type", choices=["claude", "codex"])
    set_p.add_argument("token_id", type=int)
    set_p.set_defaults(func=cmd_token_set)

    usage_p = token_sub.add_parser("usage", help="Show token usage")
    usage_p.add_argument("--agent-type", choices=["claude", "codex"], dest="agent_type")
    usage_p.add_argument("--window", type=int, default=24, help="Window in hours (default: 24)")
    usage_p.set_defaults(func=cmd_token_usage)

    # -- Agent Manager: rotate --
    rot_p = sub.add_parser("rotate", help="Rotate active tokens for all agent types")
    rot_p.set_defaults(func=cmd_rotate)

    # -- Replay --
    replay_p = sub.add_parser("replay", help="Replay a job by ID")
    replay_p.add_argument("job_id", type=int, help="Job ID to replay")
    replay_p.add_argument("--oauth_token", type=int, default=None,
                          help="Override token id (default: primary)")
    replay_p.add_argument("--model", type=str, default=None,
                          help="Override the model (e.g. claude-opus-4-20250514)")
    replay_p.add_argument("--exec", action="store_true",
                          help="Actually execute the command (not just display)")
    replay_p.add_argument("--json", action="store_true",
                          help="Output in JSON format")
    replay_p.set_defaults(func=cmd_replay)

    # -- Config (core_config_data) --
    cfg_set_p = sub.add_parser("config-set", help="Set a config value in core_config_data")
    cfg_set_p.add_argument("path", help="Config path (e.g. my_app/tools/mysql_prod/pass)")
    cfg_set_p.add_argument("value", help="Value to set")
    cfg_set_p.add_argument("--scope", default="default",
                           help="Config scope: default, workspace, agent_view")
    cfg_set_p.add_argument("--scope-id", type=int, default=0,
                           help="Scope ID (workspace or agent_view ID)")
    cfg_set_p.set_defaults(func=cmd_config_set)

    cfg_get_p = sub.add_parser("config-get", help="Get a config value from core_config_data")
    cfg_get_p.add_argument("path", help="Config path")
    cfg_get_p.set_defaults(func=cmd_config_get)

    cfg_list_p = sub.add_parser("config-list", help="List config values")
    cfg_list_p.add_argument("prefix", nargs="?", default="", help="Filter by path prefix (e.g. module name)")
    cfg_list_p.set_defaults(func=cmd_config_list)

    cfg_rm_p = sub.add_parser("config-remove", help="Remove a config value from DB")
    cfg_rm_p.add_argument("path", help="Config path to remove")
    cfg_rm_p.add_argument("--scope", default="default",
                          help="Config scope: default, workspace, agent_view")
    cfg_rm_p.add_argument("--scope-id", type=int, default=0,
                          help="Scope ID (workspace or agent_view ID)")
    cfg_rm_p.set_defaults(func=cmd_config_remove)

    # -- E2E tests --
    e2e_p = sub.add_parser("e2e", help="Run end-to-end tests with real LLM calls")
    e2e_p.add_argument("--oauth_token", type=int, default=None,
                        help="Override token id (default: primary)")
    e2e_p.add_argument("--keep", action="store_true",
                        help="Keep test jobs in DB (don't clean up)")
    e2e_p.add_argument("--model", type=str, default=None,
                        help="Override the model (e.g. claude-opus-4-20250514)")
    e2e_p.set_defaults(func=cmd_e2e)

    # -- Module scaffolding --
    make_p = sub.add_parser("make:module", help="Scaffold a new user module")
    make_p.add_argument("name", help="Module name (lowercase, alphanumeric + hyphens)")
    make_p.add_argument("--description", default="", help="Module description")
    make_p.add_argument("--tool", action="append", default=[], help="Tool spec: type:name:description")
    make_p.add_argument("--base-dir", default=None, dest="base_dir", help="Base directory for module")
    make_p.set_defaults(func=cmd_make_module)

    # -- Module validation --
    val_p = sub.add_parser("module:validate", help="Validate module structure and manifests")
    val_p.add_argument("name", nargs="?", default=None, help="Module name (validates all if omitted)")
    val_p.set_defaults(func=cmd_module_validate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
