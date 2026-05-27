"""OAuth credential file accessor.

Reads `~/.claude/.credentials.json` (claude.ai team subscription) and exposes
the current access token + expiry helpers. No network — pure file I/O.

The full P1 #5 main.py split (4-6h) is deferred. This module is the first
safe extraction: pure file readers with zero state dependencies. Future
splits (stream_oauth_completion, refresh loop) can land incrementally.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("mocha.oauth")

OAUTH_CRED_PATH = Path(
    os.environ.get("CLAUDE_OAUTH_CRED", "/root/.claude/.credentials.json")
)


def load_token() -> str | None:
    """Return current accessToken or None if missing/expired."""
    try:
        with open(OAUTH_CRED_PATH) as f:
            d = json.load(f)
        oauth = d.get("claudeAiOauth", {})
        token = oauth.get("accessToken")
        expires_at = oauth.get("expiresAt", 0) / 1000.0  # ms → s
        if not token or time.time() >= expires_at:
            return None
        return token
    except Exception:
        log.exception("OAuth token load failed")
        return None


def expiry_seconds() -> float | None:
    """Seconds until token expiry (negative if expired). None if unreadable."""
    try:
        with open(OAUTH_CRED_PATH) as f:
            d = json.load(f)
        exp = d.get("claudeAiOauth", {}).get("expiresAt", 0) / 1000.0
        return exp - time.time()
    except Exception:
        return None
