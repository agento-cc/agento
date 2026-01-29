from __future__ import annotations

from .base import Channel

_CHANNELS: dict[str, Channel] = {}


def get_channel(source: str) -> Channel:
    """Look up a channel by its source name (matches jobs.source)."""
    channel = _CHANNELS.get(source)
    if channel is None:
        raise ValueError(
            f"Unknown channel: {source!r}. Registered: {list(_CHANNELS.keys())}. "
            f"Has bootstrap() been called?"
        )
    return channel


def register_channel(channel: Channel) -> None:
    """Register a new channel at runtime."""
    _CHANNELS[channel.name] = channel


def clear() -> None:
    """Reset registry (for testing)."""
    _CHANNELS.clear()
