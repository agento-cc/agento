from __future__ import annotations

import argparse
import getpass
import json
import sys
from datetime import UTC, datetime

from ..db import get_connection_or_exit
from ..log import get_logger
from .runtime import _load_framework_config


def _mask(secret: str) -> str:
    """Return secret with all but first 4 + last 4 chars replaced by '*'.
    Secrets of length <= 8 are fully masked."""
    if len(secret) <= 8:
        return "*" * len(secret)
    return f"{secret[:4]}{'*' * (len(secret) - 8)}{secret[-4:]}"


def _read_secret(prompt: str) -> str:
    """Read a one-line secret from stdin.

    TTY → ``getpass.getpass`` (echo suppressed).
    Pipe/redirect → one line from ``sys.stdin``.
    Exits with an error if the result is empty after stripping."""
    raw = getpass.getpass(prompt) if sys.stdin.isatty() else sys.stdin.readline()
    secret = raw.strip()
    if not secret:
        print("No secret provided on stdin.", file=sys.stderr)
        sys.exit(1)
    return secret


class TokenRegisterCommand:
    @property
    def name(self) -> str:
        return "token:register"

    @property
    def shortcut(self) -> str:
        return "to:reg"

    @property
    def help(self) -> str:
        return "Register a new token (credentials stored encrypted in DB)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("agent_type", choices=["claude", "codex"])
        parser.add_argument("label")
        parser.add_argument("--token-limit", type=int, default=0, dest="token_limit")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--with-api-key", dest="with_api_key", action="store_true",
            help="Read provider API key from stdin (piped/redirected) or "
                 "interactive prompt (input hidden). Codex: OpenAI key. "
                 "Claude: Anthropic key.",
        )
        mode.add_argument(
            "--with-access-token", dest="with_access_token", action="store_true",
            help="Read access-token JWT from stdin or interactive prompt "
                 "(Codex only). Skips interactive OAuth.",
        )

    def execute(self, args: argparse.Namespace) -> None:
        from ..agent_manager import AgentProvider, register_token
        from ..event_manager import get_event_manager
        from ..events import TokenRegisteredEvent

        db_config, _, _ = _load_framework_config()
        logger = get_logger("agent-manager")

        agent_type = AgentProvider(args.agent_type)
        credentials, token_type = _resolve_credentials(args, agent_type, logger)

        conn = get_connection_or_exit(db_config)
        try:
            token = register_token(
                conn,
                agent_type=agent_type,
                label=args.label,
                credentials=credentials,
                token_limit=args.token_limit,
                type=token_type,
                logger=logger,
            )
            conn.commit()
            print(f"Registered token: id={token.id} label={token.label} type={token.type}")
        finally:
            conn.close()

        get_event_manager().dispatch(
            "token_register_after",
            TokenRegisteredEvent(
                agent_type=agent_type.value,
                token_id=token.id,
                label=token.label,
                credentials=credentials,
                type=token.type,
            ),
        )


def _resolve_credentials(args: argparse.Namespace, agent_type, logger) -> tuple[dict, str]:
    """Resolve registration input to (credentials_dict, type)."""
    from ..agent_manager import auth as auth_module
    from ..agent_manager.auth import AuthenticationError, authenticate_interactive

    # 1. Explicit credential flags (api_key / access_token)
    if args.with_access_token or args.with_api_key:
        strategy = auth_module.get_auth_strategy(agent_type)
        if strategy is None:
            print(f"Error: no auth strategy registered for {agent_type.value}", file=sys.stderr)
            sys.exit(1)

        flag = "access_token" if args.with_access_token else "api_key"
        method_name = f"register_from_{flag}"
        if not hasattr(strategy, method_name):
            print(
                f"Error: --with-{flag.replace('_', '-')} is not supported for {agent_type.value}",
                file=sys.stderr,
            )
            sys.exit(1)

        secret = _read_secret(
            f"Paste {flag.replace('_', ' ')} for {agent_type.value} "
            f"(input hidden, press Enter when done): "
        )
        # Masked echo on stderr so operators can sanity-check the right secret
        # was read — never the full value.
        print(f"Read {flag} from stdin: {_mask(secret)}", file=sys.stderr)

        try:
            credentials, token_type = getattr(strategy, method_name)(secret)
        except AuthenticationError as exc:
            print(f"Registration rejected: {exc}", file=sys.stderr)
            sys.exit(1)
        return credentials, token_type

    # 2. Interactive OAuth (no flags)
    if not sys.stdin.isatty():
        print("Error: interactive auth requires a TTY. "
              "Use: docker compose exec -it cron ...", file=sys.stderr)
        sys.exit(1)
    try:
        auth_result = authenticate_interactive(agent_type, logger)
    except AuthenticationError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)
    credentials = {
        "subscription_key": auth_result.subscription_key,
        "refresh_token": auth_result.refresh_token,
        "expires_at": auth_result.expires_at,
        "subscription_type": auth_result.subscription_type,
        "id_token": auth_result.id_token,
        "raw_auth": auth_result.raw_auth,
    }
    return credentials, "oauth"


class TokenRefreshCommand:
    @property
    def name(self) -> str:
        return "token:refresh"

    @property
    def shortcut(self) -> str:
        return "to:ref"

    @property
    def help(self) -> str:
        return "Re-authenticate an existing token (interactive OAuth)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("token_id", type=int, help="Token ID to refresh")

    def execute(self, args: argparse.Namespace) -> None:
        from ..agent_manager import register_token
        from ..agent_manager.auth import AuthenticationError, authenticate_interactive
        from ..agent_manager.token_store import get_token

        db_config, _, _ = _load_framework_config()
        logger = get_logger("agent-manager")

        conn = get_connection_or_exit(db_config)
        try:
            token = get_token(conn, args.token_id)
            if token is None:
                print(f"Error: token not found: id={args.token_id}", file=sys.stderr)
                sys.exit(1)
            if not token.enabled:
                print(f"Error: token is disabled: id={args.token_id}", file=sys.stderr)
                sys.exit(1)
        finally:
            conn.close()

        if not sys.stdin.isatty():
            print("Error: interactive auth requires a TTY. "
                  "Use: docker compose exec -it cron ...", file=sys.stderr)
            sys.exit(1)

        print(f"Refreshing token [{token.id}] {token.agent_type.value} {token.label}")

        try:
            auth_result = authenticate_interactive(token.agent_type, logger)
        except AuthenticationError as exc:
            print(f"Authentication failed: {exc}", file=sys.stderr)
            sys.exit(1)

        credentials = {
            "subscription_key": auth_result.subscription_key,
            "refresh_token": auth_result.refresh_token,
            "expires_at": auth_result.expires_at,
            "subscription_type": auth_result.subscription_type,
            "id_token": auth_result.id_token,
            "raw_auth": auth_result.raw_auth,
        }

        conn = get_connection_or_exit(db_config)
        try:
            refreshed = register_token(
                conn,
                agent_type=token.agent_type,
                label=token.label,
                credentials=credentials,
                token_limit=token.token_limit,
                logger=logger,
            )
            conn.commit()
        finally:
            conn.close()

        from ..event_manager import get_event_manager
        from ..events import TokenRefreshedEvent
        get_event_manager().dispatch(
            "token_refresh_after",
            TokenRefreshedEvent(
                agent_type=token.agent_type.value,
                token_id=refreshed.id,
                label=refreshed.label,
                credentials=credentials,
                type=refreshed.type,
            ),
        )

        print(f"Token [{token.id}] refreshed successfully.")


def _humanize_delta(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "never"
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delta = now - when
    secs = int(delta.total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _format_expiry(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "never"
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    if when <= now:
        return f"expired ({_humanize_delta(when, now)})"
    delta = when - now
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"in {secs}s"
    if secs < 3600:
        return f"in {secs // 60}m"
    if secs < 86400:
        return f"in {secs // 3600}h"
    return f"in {secs // 86400}d"


class TokenListCommand:
    @property
    def name(self) -> str:
        return "token:list"

    @property
    def shortcut(self) -> str:
        return "to:li"

    @property
    def help(self) -> str:
        return "List registered tokens"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--agent-type", choices=["claude", "codex"], dest="agent_type")
        parser.add_argument("--all", action="store_true", help="Include disabled tokens")
        parser.add_argument("--json", action="store_true")

    def execute(self, args: argparse.Namespace) -> None:
        from ..agent_manager import AgentProvider, get_usage_summaries, list_tokens

        db_config, _, am_config = _load_framework_config()
        conn = get_connection_or_exit(db_config)
        try:
            agent_type = AgentProvider(args.agent_type) if args.agent_type else None
            tokens = list_tokens(conn, agent_type=agent_type, enabled_only=not args.all)

            usage_map: dict[int, object] = {}
            agent_types_seen = {t.agent_type for t in tokens}
            for at in agent_types_seen:
                summaries = get_usage_summaries(conn, at.value, am_config.usage_window_hours)
                for s in summaries:
                    usage_map[s.token_id] = s
        finally:
            conn.close()

        now = datetime.now(UTC)

        if args.json:
            data = []
            for t in tokens:
                s = usage_map.get(t.id)
                used = s.total_tokens if s else 0
                calls = s.call_count if s else 0
                pct_free = round((t.token_limit - used) / t.token_limit * 100, 1) if t.token_limit > 0 else None
                data.append({
                    "id": t.id,
                    "agent_type": t.agent_type.value,
                    "type": t.type,
                    "priority": t.priority,
                    "label": t.label,
                    "status": t.status.value,
                    "error_msg": t.error_msg,
                    "used_at": t.used_at.isoformat() if t.used_at else None,
                    "expires_at": t.expires_at.isoformat() if t.expires_at else None,
                    "token_limit": t.token_limit,
                    "tokens_used": used,
                    "call_count": calls,
                    "pct_free": pct_free,
                    "enabled": t.enabled,
                })
            print(json.dumps(data, indent=2))
            return

        if not tokens:
            print("No tokens found.")
            return

        for t in tokens:
            s = usage_map.get(t.id)
            used = s.total_tokens if s else 0
            if t.token_limit > 0:
                pct_free = round((t.token_limit - used) / t.token_limit * 100, 1)
                usage_str = f"used={used}/{t.token_limit} ({pct_free}% free)"
            else:
                usage_str = f"used={used}/unlimited"
            status_str = f"status={t.status.value}"
            used_at_str = f"last_used={_humanize_delta(t.used_at, now)}"
            expires_str = f"expires={_format_expiry(t.expires_at, now)}"
            type_str = f"type={t.type}"
            prio_str = f"priority={t.priority}"
            line = (
                f"  [{t.id}] {t.agent_type.value:8} {t.label:20} "
                f"{type_str:28} {prio_str:12} "
                f"{usage_str}  {status_str}  {used_at_str}  {expires_str}"
            )
            print(line)
            if t.status.value == "error" and t.error_msg:
                snippet = t.error_msg[:180]
                if len(t.error_msg) > 180:
                    snippet += "…"
                print(f"      ! {snippet}")


class TokenDeregisterCommand:
    @property
    def name(self) -> str:
        return "token:deregister"

    @property
    def shortcut(self) -> str:
        return "to:de"

    @property
    def help(self) -> str:
        return "Disable a token"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("token_id", type=int)

    def execute(self, args: argparse.Namespace) -> None:
        from ..agent_manager import deregister_token

        db_config, _, _ = _load_framework_config()
        logger = get_logger("agent-manager")
        conn = get_connection_or_exit(db_config)
        try:
            found = deregister_token(conn, token_id=args.token_id, logger=logger)
            conn.commit()
            if found:
                print(f"Deregistered token: id={args.token_id}")
            else:
                print(f"Token not found: id={args.token_id}", file=sys.stderr)
                sys.exit(1)
        finally:
            conn.close()


class TokenMarkErrorCommand:
    @property
    def name(self) -> str:
        return "token:mark-error"

    @property
    def shortcut(self) -> str:
        return "to:me"

    @property
    def help(self) -> str:
        return "Manually flag a token as unhealthy (status=error) so the pool stops using it"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("token_id", type=int)
        parser.add_argument("message", help="Human-readable reason, stored in error_msg")

    def execute(self, args: argparse.Namespace) -> None:
        from ..agent_manager import mark_token_error
        from ..agent_manager.token_store import get_token
        from ..event_manager import get_event_manager
        from ..events import TokenAuthFailedEvent

        db_config, _, _ = _load_framework_config()
        logger = get_logger("agent-manager")
        conn = get_connection_or_exit(db_config)
        try:
            token = get_token(conn, args.token_id)
            found = mark_token_error(conn, args.token_id, args.message, logger=logger)
            conn.commit()
            if found:
                print(f"Token [{args.token_id}] marked as error: {args.message}")
            else:
                print(f"Token not found: id={args.token_id}", file=sys.stderr)
                sys.exit(1)
        finally:
            conn.close()

        if token is not None:
            get_event_manager().dispatch(
                "token_auth_failed_after",
                TokenAuthFailedEvent(
                    agent_type=token.agent_type.value,
                    token_id=args.token_id,
                    error_msg=args.message,
                    job_id=None,
                ),
            )


class TokenResetCommand:
    @property
    def name(self) -> str:
        return "token:reset"

    @property
    def shortcut(self) -> str:
        return "to:res"

    @property
    def help(self) -> str:
        return "Clear error status on a token so the pool starts using it again"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("token_id", type=int)

    def execute(self, args: argparse.Namespace) -> None:
        from ..agent_manager import clear_token_error

        db_config, _, _ = _load_framework_config()
        logger = get_logger("agent-manager")
        conn = get_connection_or_exit(db_config)
        try:
            found = clear_token_error(conn, args.token_id, logger=logger)
            conn.commit()
            if found:
                print(f"Token [{args.token_id}] status cleared (ok)")
            else:
                print(f"Token not found: id={args.token_id}", file=sys.stderr)
                sys.exit(1)
        finally:
            conn.close()


class TokenSetPriorityCommand:
    @property
    def name(self) -> str:
        return "token:set-priority"

    @property
    def shortcut(self) -> str:
        return "to:sp"

    @property
    def help(self) -> str:
        return "Set token selection priority (lower wins; ties broken by LRU)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("token_id", type=int)
        parser.add_argument("priority", type=int, help="Integer; lower = used first; default 0")

    def execute(self, args: argparse.Namespace) -> None:
        from ..agent_manager.token_store import set_token_priority

        db_config, _, _ = _load_framework_config()
        logger = get_logger("agent-manager")
        conn = get_connection_or_exit(db_config)
        try:
            found = set_token_priority(conn, args.token_id, args.priority, logger=logger)
            conn.commit()
            if found:
                print(f"Token [{args.token_id}] priority set to {args.priority}")
            else:
                print(f"Token not found: id={args.token_id}", file=sys.stderr)
                sys.exit(1)
        finally:
            conn.close()


class TokenUsageCommand:
    @property
    def name(self) -> str:
        return "token:usage"

    @property
    def shortcut(self) -> str:
        return "to:us"

    @property
    def help(self) -> str:
        return "Show token usage"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--agent-type", choices=["claude", "codex"], dest="agent_type")
        parser.add_argument("--window", type=int, default=24, help="Window in hours (default: 24)")

    def execute(self, args: argparse.Namespace) -> None:
        from ..agent_manager import AgentProvider, get_usage_summaries, list_tokens

        db_config, _, _ = _load_framework_config()
        conn = get_connection_or_exit(db_config)
        window = args.window
        try:
            agent_types = [AgentProvider(args.agent_type)] if args.agent_type else list(AgentProvider)
            for at in agent_types:
                tokens = list_tokens(conn, agent_type=at)
                summaries = get_usage_summaries(conn, at.value, window)
                usage_map = {s.token_id: s for s in summaries}
                for t in tokens:
                    s = usage_map.get(t.id)
                    used = s.total_tokens if s else 0
                    calls = s.call_count if s else 0
                    limit = t.token_limit if t.token_limit else "unlimited"
                    print(f"  [{t.id}] {at.value:8} {t.label:20} used={used:>10} calls={calls:>5} limit={limit}")
        finally:
            conn.close()
