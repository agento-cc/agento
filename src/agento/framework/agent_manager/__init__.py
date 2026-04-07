"""Agent Manager — multi-token orchestration for LLM agent providers."""

from .active import read_credentials, resolve_active_token, update_active_token
from .auth import AuthenticationError, AuthResult, authenticate_interactive, get_available_providers, save_credentials
from .config import AgentManagerConfig
from .models import AgentProvider, RotationResult, Token, UsageSummary
from .rotator import rotate_all, rotate_tokens, select_best_token
from .token_store import deregister_token, get_token, get_token_by_path, list_tokens, register_token, set_primary_token
from .usage_store import get_usage_summaries, get_usage_summary, record_usage

__all__ = [
    "AgentManagerConfig",
    "AgentProvider",
    "AuthResult",
    "AuthenticationError",
    "RotationResult",
    "Token",
    "UsageSummary",
    "authenticate_interactive",
    "get_available_providers",
    "deregister_token",
    "get_token",
    "get_token_by_path",
    "get_usage_summaries",
    "get_usage_summary",
    "list_tokens",
    "read_credentials",
    "record_usage",
    "register_token",
    "resolve_active_token",
    "rotate_all",
    "rotate_tokens",
    "save_credentials",
    "select_best_token",
    "set_primary_token",
    "update_active_token",
]
