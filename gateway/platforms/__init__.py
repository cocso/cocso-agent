"""
Platform adapters for messaging integrations.

Each adapter handles:
- Receiving messages from a platform
- Sending messages/responses back
- Platform-specific authentication
- Message formatting and media handling

COCSO ships Discord, Slack, and Telegram adapters; they are loaded by
gateway/run.py based on the credentials present in ~/.cocso/.env, not
imported eagerly here.
"""

from .base import BasePlatformAdapter, MessageEvent, SendResult

__all__ = [
    "BasePlatformAdapter",
    "MessageEvent",
    "SendResult",
]
