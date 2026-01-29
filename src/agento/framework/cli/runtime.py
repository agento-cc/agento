from __future__ import annotations

import argparse
import json
import logging

from ..agent_manager.config import AgentManagerConfig
from ..agent_manager.token_store import get_primary_token, get_token
from ..consumer_config import ConsumerConfig
from ..database_config import DatabaseConfig
from ..db import get_connection
from ..log import get_logger
from ..runner_factory import create_runner


def _load_framework_config() -> tuple[DatabaseConfig, ConsumerConfig, AgentManagerConfig]:
    """Load framework-level config from env vars.

    Returns (DatabaseConfig, ConsumerConfig, AgentManagerConfig).
    For commands that don't need module config — just DB access and framework tuning.
    """
    return (
        DatabaseConfig.from_env(),
        ConsumerConfig.from_env(),
        AgentManagerConfig.from_env(),
    )


def _resolve_token(token_id: int | None = None):
    """Resolve a Token by explicit id, or fall back to the global primary."""

    db_config, _, _ = _load_framework_config()
    conn = get_connection(db_config)
    try:
        if token_id is not None:
            token = get_token(conn, token_id)
            if token is None:
                raise ValueError(f"Token not found: id={token_id}")
            if not token.enabled:
                raise ValueError(f"Token disabled: id={token_id}")
            return token
        primary = get_primary_token(conn)
        if primary is None:
            raise RuntimeError(
                "No primary token set. Run: agent token set <claude|codex> <id>"
            )
        return primary
    finally:
        conn.close()


def _make_runner(logger: logging.Logger | None = None) -> object:
    token = _resolve_token()
    _, consumer_config, _ = _load_framework_config()
    return create_runner(token.agent_type, logger=logger, dry_run=consumer_config.disable_llm)


def cmd_consumer(args: argparse.Namespace) -> None:
    from ..bootstrap import bootstrap
    from ..consumer import Consumer

    db_config, consumer_config, _ = _load_framework_config()
    conn = get_connection(db_config)
    try:
        bootstrap(db_conn=conn)
    finally:
        conn.close()

    logger = get_logger("consumer", "/app/logs/consumer.log")
    consumer = Consumer(db_config, consumer_config, logger)
    consumer.run()


def cmd_setup_upgrade(args: argparse.Namespace) -> None:
    from ..setup import setup_upgrade

    db_config, _, _ = _load_framework_config()
    logger = get_logger("setup")
    conn = get_connection(db_config)
    try:
        result = setup_upgrade(conn, logger, dry_run=args.dry_run)

        if args.dry_run:
            if not result.has_work:
                print("Nothing to do.")
                return
            print("Pending setup work:\n")
            if result.framework_migrations:
                print(f"  Framework migrations ({len(result.framework_migrations)}):")
                for v in result.framework_migrations:
                    print(f"    {v}")
            for mod, versions in result.module_migrations.items():
                print(f"  Module migrations [{mod}] ({len(versions)}):")
                for v in versions:
                    print(f"    {v}")
            for mod, patches in result.data_patches.items():
                print(f"  Data patches [{mod}] ({len(patches)}):")
                for p in patches:
                    print(f"    {p}")
            if result.cron_changed:
                print("  Crontab: would be updated")
        else:
            if not result.has_work:
                print("Nothing to do.")
                return
            if result.framework_migrations:
                print(f"Applied {len(result.framework_migrations)} framework migration(s)")
            for mod, versions in result.module_migrations.items():
                print(f"Applied {len(versions)} migration(s) for {mod}")
            for mod, patches in result.data_patches.items():
                print(f"Applied {len(patches)} data patch(es) for {mod}")
            if result.cron_changed:
                print("Crontab updated")
    finally:
        conn.close()


def cmd_replay(args: argparse.Namespace) -> None:
    from ..bootstrap import bootstrap
    from ..replay import build_replay_command, fetch_job_for_replay

    db_config, consumer_config, _ = _load_framework_config()
    conn = get_connection(db_config)
    try:
        bootstrap(db_conn=conn)
    finally:
        conn.close()

    job = fetch_job_for_replay(args.job_id, db_config)

    # Resolve agent_type from --oauth_token or primary token or job record
    token = _resolve_token(args.oauth_token) if args.oauth_token else None
    agent_type_override = token.agent_type.value if token else None

    replay = build_replay_command(
        job,
        agent_type_override=agent_type_override,
        model_override=args.model,
    )

    if args.exec:
        logger = get_logger("replay", "/app/logs/replay.log", stderr=False)
        # Use explicit token or fall back to primary
        run_token = token or _resolve_token()
        runner = create_runner(
            run_token.agent_type, logger=logger, dry_run=consumer_config.disable_llm
        )
        result = runner.run(replay.prompt, model=args.model)
        print(json.dumps({
            "job_id": job.id,
            "agent_type": result.agent_type or replay.agent_type,
            "model": result.model or replay.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
            "duration_ms": result.duration_ms,
            "subtype": result.subtype,
            "output_preview": result.raw_output[:500],
        }, indent=2))
    elif args.json:
        print(json.dumps({
            "job_id": job.id,
            "type": job.type.value,
            "source": job.source,
            "reference_id": job.reference_id,
            "agent_type": replay.agent_type,
            "model": replay.model,
            "command": replay.args,
            "shell_command": replay.shell_command,
            "prompt_length": len(replay.prompt),
            "prompt_preview": replay.prompt[:200],
        }, indent=2, ensure_ascii=False))
    else:
        print(f"Job #{job.id} ({job.type.value}) ref={job.reference_id}")
        print(f"Agent: {replay.agent_type}  Model: {replay.model or 'default'}")
        print(f"Prompt ({len(replay.prompt)} chars):")
        print("---")
        print(replay.prompt)
        print("---")
        print()
        print("Command:")
        print(f"  {replay.shell_command}")


def cmd_rotate(args: argparse.Namespace) -> None:
    from ..agent_manager import rotate_all

    db_config, _, am_config = _load_framework_config()
    logger = get_logger("agent-manager")
    conn = get_connection(db_config)
    try:
        results = rotate_all(conn, am_config, logger)
        conn.commit()
        if not results:
            print("No rotation results (no tokens registered?).")
            return
        for r in results:
            print(f"  {r.agent_type.value:8} prev={r.previous_token_id or '-':>4} new={r.new_token_id:>4} reason={r.reason}")
    finally:
        conn.close()


def cmd_e2e(args: argparse.Namespace) -> None:
    from ..e2e import cmd_e2e

    cmd_e2e(args)
