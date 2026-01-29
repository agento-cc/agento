"""Application bootstrap — scan modules, populate registries, resolve config."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .agent_manager.auth import clear_auth_strategies, register_auth_strategy
from .agent_manager.models import AgentProvider
from .channels import registry as channel_registry
from .commands import clear as clear_commands
from .commands import register_command
from .config_resolver import load_db_overrides, read_config_defaults, resolve_module_config
from .dependency_resolver import resolve_order
from .event_manager import ObserverEntry, get_event_manager
from .event_manager import clear as clear_event_manager
from .events import ModuleLoadedEvent, ModuleReadyEvent, ModuleRegisterEvent, ModuleShutdownEvent
from .job_models import AgentType
from .module_loader import ModuleManifest, import_class, scan_modules
from .router_registry import clear as clear_routers
from .router_registry import register_router
from .runner_factory import clear as clear_runners
from .runner_factory import register_runner as register_runner_factory
from .workflows import clear as clear_workflows
from .workflows import register_workflow
from .workflows.blank import BlankWorkflow

logger = logging.getLogger(__name__)


CORE_MODULES_DIR = str(Path(__file__).parent.parent / "modules")
USER_MODULES_DIR = "/app/code"

# Module config registry — {module_name: {field: value}}
_MODULE_CONFIGS: dict[str, dict[str, Any]] = {}

# Manifest registry — for shutdown hooks and introspection
_MANIFESTS: list[ModuleManifest] = []


def set_module_config(module_name: str, config: Any) -> None:
    """Override module config (for testing or manual setup)."""
    _MODULE_CONFIGS[module_name] = config


def get_module_config(module_name: str) -> dict[str, Any]:
    """Get resolved config for a module. Returns empty dict if module has no config."""
    return _MODULE_CONFIGS.get(module_name, {})


def get_manifests() -> list[ModuleManifest]:
    """Get loaded module manifests (dependency order)."""
    return list(_MANIFESTS)


def dispatch_shutdown() -> None:
    """Dispatch module_shutdown events in reverse dependency order."""
    em = get_event_manager()
    for m in reversed(_MANIFESTS):
        em.dispatch("module_shutdown", ModuleShutdownEvent(name=m.name, path=m.path))


def bootstrap(
    core_dir: str = CORE_MODULES_DIR,
    user_dir: str = USER_MODULES_DIR,
    *,
    db_conn=None,
) -> list[ModuleManifest]:
    """Scan core + user modules, populate all registries, resolve config.

    Core modules (ship with agento) are loaded first,
    user modules can override them (like Magento app/code/ vs vendor/).
    Clears registries first for idempotent re-bootstrap (supports module add/remove).

    Args:
        db_conn: Optional DB connection for loading core_config_data overrides.
                 When None (e.g. in tests), only ENV + config.json + defaults are used.
    """
    channel_registry.clear()
    clear_workflows()
    clear_runners()
    clear_auth_strategies()
    clear_commands()
    clear_routers()
    clear_event_manager()
    _MODULE_CONFIGS.clear()
    _MANIFESTS.clear()

    manifests = resolve_order(scan_modules(core_dir) + scan_modules(user_dir))

    # Resolve module configs (3-level fallback)
    db_overrides = load_db_overrides(db_conn)
    for m in manifests:
        if m.config:
            config_defaults = read_config_defaults(m.path)
            resolved = resolve_module_config(m, config_defaults, db_overrides)
            # If module declares a config_class, convert dict to typed dataclass
            config_class_path = m.provides.get("config_class")
            if config_class_path:
                try:
                    cls = import_class(m.path, config_class_path)
                    resolved = cls.from_dict(resolved)
                except Exception:
                    logger.exception(
                        "Failed to load config_class %r from module %s, using dict",
                        config_class_path, m.name,
                    )
            _MODULE_CONFIGS[m.name] = resolved

    em = get_event_manager()

    for m in manifests:
        # Load observers first so they're registered before events fire
        _load_observers(m)

        # Dispatch module_register (module just loaded, before capabilities)
        em.dispatch(
            "module_register",
            ModuleRegisterEvent(
                name=m.name, path=m.path, config=_MODULE_CONFIGS.get(m.name, {})
            ),
        )

        # Register capabilities
        _load_channels(m)
        _load_workflows(m)
        _load_runtimes(m)
        _load_auth_strategies(m)
        _load_commands(m)
        _load_routers(m)

        # Dispatch module_loaded (capabilities registered)
        em.dispatch("module_loaded", ModuleLoadedEvent(name=m.name, path=m.path))

    # BlankWorkflow is always available (core, not tied to any integration)
    register_workflow(AgentType.BLANK, BlankWorkflow)

    # Store manifests for shutdown and introspection
    _MANIFESTS.extend(manifests)

    # Dispatch module_ready (all modules loaded, safe to query registries)
    for m in manifests:
        em.dispatch("module_ready", ModuleReadyEvent(name=m.name, path=m.path))

    logger.info(
        "Bootstrap: loaded %d module(s): %s",
        len(manifests),
        ", ".join(m.name for m in manifests),
    )
    return manifests


def _load_observers(m: ModuleManifest) -> None:
    for event_name, observer_list in m.observers.items():
        for decl in observer_list:
            try:
                cls = import_class(m.path, decl["class"])
                entry = ObserverEntry(
                    name=decl["name"],
                    observer_class=cls,
                    order=decl.get("order", 1000),
                )
                get_event_manager().register(event_name, entry)
                logger.debug(
                    "Registered observer %r for event %r from module %s",
                    decl["name"], event_name, m.name,
                )
            except Exception:
                logger.exception(
                    "Failed to load observer %r from module %s",
                    decl.get("name"), m.name,
                )


def _load_channels(m: ModuleManifest) -> None:
    for decl in m.provides.get("channels", []):
        try:
            cls = import_class(m.path, decl["class"])
            channel_registry.register_channel(cls())
            logger.debug("Registered channel %r from module %s", decl["name"], m.name)
        except Exception:
            logger.exception("Failed to load channel %r from module %s", decl.get("name"), m.name)


def _load_workflows(m: ModuleManifest) -> None:
    for decl in m.provides.get("workflows", []):
        try:
            cls = import_class(m.path, decl["class"])
            agent_type = AgentType(decl["type"])
            register_workflow(agent_type, cls)
            logger.debug("Registered workflow %r from module %s", decl["type"], m.name)
        except Exception:
            logger.exception("Failed to load workflow %r from module %s", decl.get("type"), m.name)


def _load_runtimes(m: ModuleManifest) -> None:
    for decl in m.provides.get("runtimes", []):
        try:
            cls = import_class(m.path, decl["class"])

            def _make_factory(runner_cls: type):
                def factory(**kwargs: object):
                    return runner_cls(**kwargs)
                return factory

            provider = AgentProvider(decl["provider"])
            register_runner_factory(provider, _make_factory(cls))
            logger.debug("Registered runtime %r from module %s", decl["provider"], m.name)
        except Exception:
            logger.exception("Failed to load runtime %r from module %s", decl.get("provider"), m.name)


def _load_auth_strategies(m: ModuleManifest) -> None:
    for decl in m.provides.get("auth_strategies", []):
        try:
            cls = import_class(m.path, decl["class"])
            provider = AgentProvider(decl["provider"])
            register_auth_strategy(provider, cls())
            logger.debug("Registered auth strategy %r from module %s", decl["provider"], m.name)
        except Exception:
            logger.exception("Failed to load auth strategy %r from module %s", decl.get("provider"), m.name)


def _load_commands(m: ModuleManifest) -> None:
    for decl in m.provides.get("commands", []):
        try:
            cls = import_class(m.path, decl["class"])
            register_command(cls())
            logger.debug("Registered command %r from module %s", decl["name"], m.name)
        except Exception:
            logger.exception("Failed to load command %r from module %s", decl.get("name"), m.name)


def _load_routers(m: ModuleManifest) -> None:
    for decl in m.provides.get("routers", []):
        try:
            cls = import_class(m.path, decl["class"])
            register_router(cls(), order=decl.get("order", 1000))
            logger.debug("Registered router %r from module %s", decl["name"], m.name)
        except Exception:
            logger.exception("Failed to load router %r from module %s", decl.get("name"), m.name)
