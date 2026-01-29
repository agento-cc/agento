from __future__ import annotations

import argparse
import json
import os
import sys

from ..db import get_connection
from ..log import get_logger
from .runtime import _load_framework_config


def cmd_token_refresh(args: argparse.Namespace) -> None:
    from ..agent_manager import update_active_token
    from ..agent_manager.auth import AuthenticationError, authenticate_interactive, save_credentials
    from ..agent_manager.token_store import get_token

    db_config, _, am_config = _load_framework_config()
    logger = get_logger("agent-manager")

    conn = get_connection(db_config)
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
    print(f"Credentials: {token.credentials_path}")

    try:
        auth_result = authenticate_interactive(token.agent_type, logger)
    except AuthenticationError as exc:
        print(f"Authentication failed: {exc}", file=sys.stderr)
        sys.exit(1)

    save_credentials(auth_result, token.credentials_path)
    print(f"Credentials saved to: {token.credentials_path}")

    # Update active symlink if this is the primary token
    if token.is_primary:
        update_active_token(am_config, token.agent_type, token, logger)
        print("Active symlink updated.")

    print(f"Token [{token.id}] refreshed successfully.")


def cmd_token_register(args: argparse.Namespace) -> None:
    from ..agent_manager import AgentProvider, register_token
    from ..agent_manager.auth import AuthenticationError, authenticate_interactive, save_credentials

    db_config, _, am_config = _load_framework_config()
    logger = get_logger("agent-manager")

    credentials_path = args.credentials_path
    agent_type = AgentProvider(args.agent_type)

    if credentials_path is not None:
        # Validate the provided credentials file
        if not os.path.isfile(credentials_path):
            print(f"Error: credentials file not found: {credentials_path}", file=sys.stderr)
            sys.exit(1)
        try:
            with open(credentials_path) as f:
                creds = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Error: cannot read credentials file: {exc}", file=sys.stderr)
            sys.exit(1)
        if "subscription_key" not in creds:
            print(f"Error: credentials file missing 'subscription_key': {credentials_path}", file=sys.stderr)
            sys.exit(1)
        tokens_dir = am_config.tokens_dir
        if not os.path.abspath(credentials_path).startswith(os.path.abspath(tokens_dir)):
            print(f"Error: credentials file must be inside tokens dir ({tokens_dir}): {credentials_path}",
                  file=sys.stderr)
            sys.exit(1)

    if credentials_path is None:
        # Interactive OAuth flow
        if not sys.stdin.isatty():
            print("Error: interactive auth requires a TTY. "
                  "Use: docker compose exec -it cron ...", file=sys.stderr)
            sys.exit(1)

        credentials_path = os.path.join(
            am_config.tokens_dir,
            f"{args.agent_type}_{args.label}.json",
        )

        try:
            auth_result = authenticate_interactive(agent_type, logger)
        except AuthenticationError as exc:
            print(f"Authentication failed: {exc}", file=sys.stderr)
            sys.exit(1)

        save_credentials(auth_result, credentials_path)
        print(f"Credentials saved to: {credentials_path}")

    conn = get_connection(db_config)
    try:
        token = register_token(
            conn,
            agent_type=agent_type,
            label=args.label,
            credentials_path=credentials_path,
            token_limit=args.token_limit,
            model=args.model,
            logger=logger,
        )
        conn.commit()
        model_info = f" model={token.model}" if token.model else ""
        print(f"Registered token: id={token.id} label={token.label}{model_info}")
    finally:
        conn.close()


def cmd_token_list(args: argparse.Namespace) -> None:
    from ..agent_manager import AgentProvider, get_usage_summaries, list_tokens

    db_config, _, am_config = _load_framework_config()
    conn = get_connection(db_config)
    try:
        agent_type = AgentProvider(args.agent_type) if args.agent_type else None
        tokens = list_tokens(conn, agent_type=agent_type, enabled_only=not args.all)

        # Build usage map for all relevant agent types
        usage_map: dict[int, object] = {}
        agent_types_seen = {t.agent_type for t in tokens}
        for at in agent_types_seen:
            summaries = get_usage_summaries(conn, at.value, am_config.usage_window_hours)
            for s in summaries:
                usage_map[s.token_id] = s
    finally:
        conn.close()

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
                "label": t.label,
                "model": t.model,
                "is_primary": t.is_primary,
                "credentials_path": t.credentials_path,
                "token_limit": t.token_limit,
                "tokens_used": used,
                "call_count": calls,
                "pct_free": pct_free,
                "enabled": t.enabled,
            })
        print(json.dumps(data, indent=2))
    else:
        if not tokens:
            print("No tokens found.")
            return
        for t in tokens:
            s = usage_map.get(t.id)
            used = s.total_tokens if s else 0
            calls = s.call_count if s else 0
            model_str = f"model={t.model}" if t.model else "model=-"
            if t.token_limit > 0:
                pct_free = round((t.token_limit - used) / t.token_limit * 100, 1)
                usage_str = f"used={used}/{t.token_limit} ({pct_free}% free)"
            else:
                usage_str = f"used={used}/unlimited"
            primary_str = "  PRIMARY" if t.is_primary else ""
            print(f"  [{t.id}] {t.agent_type.value:8} {t.label:20} {model_str:30} {usage_str}{primary_str}")


def cmd_token_deregister(args: argparse.Namespace) -> None:
    from ..agent_manager import deregister_token

    db_config, _, _ = _load_framework_config()
    logger = get_logger("agent-manager")
    conn = get_connection(db_config)
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


def cmd_token_set(args: argparse.Namespace) -> None:
    from ..agent_manager import AgentProvider, update_active_token
    from ..agent_manager.token_store import get_token, set_primary_token

    db_config, _, am_config = _load_framework_config()
    logger = get_logger("agent-manager")
    agent_type = AgentProvider(args.agent_type)
    token_id = args.token_id

    conn = get_connection(db_config)
    try:
        found = set_primary_token(conn, agent_type, token_id, logger)
        if not found:
            print(f"Token not found or disabled: id={token_id} agent_type={args.agent_type}", file=sys.stderr)
            sys.exit(1)

        # Update the active symlink immediately
        token = get_token(conn, token_id)
        if token:
            update_active_token(am_config, agent_type, token, logger)

        conn.commit()
        model_info = f" model={token.model}" if token and token.model else ""
        print(f"Set primary token: [{token_id}] {args.agent_type}{model_info}")
    finally:
        conn.close()


def cmd_token_usage(args: argparse.Namespace) -> None:
    from ..agent_manager import AgentProvider, get_usage_summaries, list_tokens

    db_config, _, _ = _load_framework_config()
    conn = get_connection(db_config)
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
