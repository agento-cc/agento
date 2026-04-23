"""Agent Manager — multi-token orchestration for LLM agent providers."""

from .auth import AuthResult, authenticate_interactive, get_available_providers, save_credentials
from .config import AgentManagerConfig
from .errors import AuthenticationError
from .models import AgentProvider, Token, TokenStatus, UsageSummary
from .token_store import (
    clear_token_error,
    count_tokens_for_provider,
    deregister_token,
    get_token,
    list_tokens,
    mark_token_error,
    register_token,
    select_token,
)
from .usage_store import get_usage_summaries, get_usage_summary, record_usage

__all__ = [
    "AgentManagerConfig",
    "AgentProvider",
    "AuthResult",
    "AuthenticationError",
    "Token",
    "TokenStatus",
    "UsageSummary",
    "authenticate_interactive",
    "clear_token_error",
    "count_tokens_for_provider",
    "deregister_token",
    "get_available_providers",
    "get_token",
    "get_usage_summaries",
    "get_usage_summary",
    "list_tokens",
    "mark_token_error",
    "record_usage",
    "register_token",
    "save_credentials",
    "select_token",
]
