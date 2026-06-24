"""Generic message envelope used by 2xx endpoints that don't need a body."""
from __future__ import annotations

from pydantic import BaseModel


class Message(BaseModel):
    """Simple `{message: str}` response."""

    message: str