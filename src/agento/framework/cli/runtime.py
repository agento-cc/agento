from __future__ import annotations

import argparse
import json
import logging

from ..agent_manager.config import AgentManagerConfig
from ..agent_manager.token_store import get_token, select_token
from ..consumer_config import ConsumerConfig
from ..database_config import DatabaseConfig
from ..db import get_connection_or_exit
from ..log import get_logger
from ..runner_factory import create_runner


def _load_framework_config() -> tuple[DatabaseConfig, ConsumerConfig, AgentManagerConfig]:
    """Load framework-level config from env vars.

    Returns (DatabaseConfig, ConsumerConfig, AgentManagerConfig).
    For commands that don't need module config -- just DB access and framework tuning.
    """
    return (
        DatabaseConfig.from_env(),
        ConsumerConfig.from_env(),
        AgentManagerConfig.from_env(),
    )


def _resolve_token(token_id: int | None = None, agent_type=None):
    """Resolve a Token by explicit id, or pick the LRU healthy one from the pool.

    When ``token_id`` is None, ``agent_type`` must be supplied; replay paths
    derive it from the job record.
    """

    db_config, _, _ = _load_framework_config()
    conn = get_connection_or_exit(db_config)
    try:
        if token_id is not None:
            token = get_token(conn, token_id)
            if token is None:
                raise ValueError(f"Token not found: id={token_id}")
            if not token.enabled:
                raise ValueError(f"Token disabled: id={token_id}")
            return token
        if agent_type is None:
            raise RuntimeError(
                "Cannot resolve a token without --oauth_token or an agent_type. "
                "Pass --oauth_token or configure agent_view/provider."
            )
        selected = select_token(conn, agent_type)
        if selected is None:
            raise RuntimeError(
                f"No healthy tokens for agent_type={agent_type.value}. "
                f"Check: bin/agento token:list --all"
            )
        return selected
    finally:
        conn.close()


def _make_runner(logger: logging.Logger | None = None) -> object:
    token = _resolve_token()
    _, consumer_config, _ = _load_framework_config()
    return create_runner(token.agent_type, logger=logger, dry_run=consumer_config.disable_llm)


class ConsumerCommand:
    @property
    def name(self) -> str:
        return "consumer"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Start the job consumer"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        pass

    def execute(self, args: argparse.Namespace) -> None:
        from ..bootstrap import bootstrap
        from ..consumer import Consumer

        db_config, consumer_config, _ = _load_framework_config()
        conn = get_connection_or_exit(db_config)
        try:
            bootstrap(db_conn=conn)
        finally:
            conn.close()

        logger = get_logger("consumer", "/app/logs/consumer.log")
        consumer = Consumer(db_config, consumer_config, logger)
        consumer.run()


class SetupUpgradeCommand:
    @property
    def name(self) -> str:
        return "setup:upgrade"

    @property
    def shortcut(self) -> str:
        return "se:up"

    @property
    def help(self) -> str:
        return "Apply schema migrations, data patches, and install crontab"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Show pending work without applying")
        parser.add_argument("--skip-onboarding", action="store_true", dest="skip_onboarding",
                         help="Skip interactive module onboarding prompts")

    def execute(self, args: argparse.Namespace) -> None:
        import sys

        from ..dependency_resolver import DisabledDependencyError
        from ..setup import setup_upgrade

        db_config, _, _ = _load_framework_config()
        logger = get_logger("setup")
        conn = get_connection_or_exit(db_config)
        try:
            try:
                skip_onboarding = getattr(args, "skip_onboarding", False)
                result = setup_upgrade(
                    conn, logger, dry_run=args.dry_run, skip_onboarding=skip_onboarding,
                )
            except DisabledDependencyError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

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
                for mod in result.onboardings_run:
                    print(f"Onboarding completed for {mod}")
                if result.onboardings_disabled:
                    print(f"Modules disabled during onboarding: {', '.join(result.onboardings_disabled)}")
        finally:
            conn.close()


class ReplayCommand:
    @property
    def name(self) -> str:
        return "replay"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Replay a job by ID"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("job_id", type=int, help="Job ID to replay")
        parser.add_argument("--oauth_token", type=int, default=None,
                          help="Override token id (default: least-recently-used healthy token)")
        parser.add_argument("--model", type=str, default=None,
                          help="Override the model (e.g. claude-opus-4-20250514)")
        parser.add_argument("--exec", action="store_true",
                          help="Actually execute the command (not just display)")
        parser.add_argument("--json", action="store_true",
                          help="Output in JSON format")

    def execute(self, args: argparse.Namespace) -> None:
        from ..bootstrap import bootstrap
        from ..replay import build_replay_command, fetch_job_for_replay

        db_config, consumer_config, _ = _load_framework_config()
        conn = get_connection_or_exit(db_config)
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
            # Use explicit token or pick from the pool for the job's agent_type
            if token is None:
                from ..agent_manager.models import AgentProvider as _AgentProvider
                replay_agent_type = _AgentProvider(replay.agent_type)
                run_token = _resolve_token(None, agent_type=replay_agent_type)
            else:
                run_token = token
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


class PauseCommand:
    @property
    def name(self) -> str:
        return "job:pause"

    @property
    def shortcut(self) -> str:
        return "jo:pa"

    @property
    def help(self) -> str:
        return "Pause a running job (SIGTERM + keep session)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("job_id", type=int, help="Job ID to pause")

    def execute(self, args: argparse.Namespace) -> None:
        import sys

        from ..event_manager import get_event_manager
        from ..events import JobPausedEvent
        from ..job_store import pause_job

        db_config, _, _ = _load_framework_config()
        conn = get_connection_or_exit(db_config)
        try:
            job = pause_job(conn, args.job_id)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            conn.close()

        get_event_manager().dispatch("job_pause_after", JobPausedEvent(job=job))

        print(f"Job #{job.id} paused.")
        if job.session_id:
            print(f"  session_id: {job.session_id}")
        print(f"  pid: {job.pid or 'N/A'}")
        print()
        print("Resume with: agento job:resume", job.id)


class ResumeCommand:
    @property
    def name(self) -> str:
        return "job:resume"

    @property
    def shortcut(self) -> str:
        return "jo:re"

    @property
    def help(self) -> str:
        return "Resume a paused job (re-queue for consumer pickup)"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("job_id", type=int, help="Job ID to resume")

    def execute(self, args: argparse.Namespace) -> None:
        import sys

        from ..event_manager import get_event_manager
        from ..events import JobResumedEvent
        from ..job_store import resume_job

        db_config, _, _ = _load_framework_config()
        conn = get_connection_or_exit(db_config)
        try:
            job = resume_job(conn, args.job_id)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            conn.close()

        get_event_manager().dispatch("job_resume_after", JobResumedEvent(job=job))

        print(f"Job #{job.id} re-queued.")
        print(f"  session_id: {job.session_id}")
        print()
        print("Job will be picked up by the next consumer poll;")
        print(f"it will resume via session_id={job.session_id}")


class E2eCommand:
    @property
    def name(self) -> str:
        return "e2e"

    @property
    def shortcut(self) -> str:
        return ""

    @property
    def help(self) -> str:
        return "Run end-to-end tests with real LLM calls"

    def configure(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--oauth_token", type=int, default=None,
                          help="Override token id (default: least-recently-used healthy token)")
        parser.add_argument("--keep", action="store_true",
                          help="Keep test jobs in DB (don't clean up)")
        parser.add_argument("--model", type=str, default=None,
                          help="Override the model (e.g. claude-opus-4-20250514)")

    def execute(self, args: argparse.Namespace) -> None:
        from ..e2e import cmd_e2e

        cmd_e2e(args)
