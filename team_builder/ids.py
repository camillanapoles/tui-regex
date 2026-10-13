"""ID helpers — every object in the platform carries a unique prefixed ID."""
from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    """Full-length unique ID, e.g. 'gate-3f2a...'. Used as PKs."""
    return f"{prefix}-{uuid.uuid4().hex}"


def short_id(prefix: str) -> str:
    """Short unique ID, e.g. 'dev-1a2b3c4d'. Used for human-friendly names."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"
