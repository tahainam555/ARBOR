"""Small helpers for recoverable turn failures."""

from __future__ import annotations


RECOVERABLE_ERROR_MESSAGE = (
    "I hit an internal error while handling that request. "
    "Please try again in a moment."
)


def build_recoverable_error_payload(message: str | None = None) -> dict[str, object]:
    """Return the websocket error payload used for recoverable failures."""
    return {
        "type": "error",
        "message": message or RECOVERABLE_ERROR_MESSAGE,
        "recoverable": True,
    }
