"""Mocha prompt template loader.

Templates use `string.Template` ($VAR syntax — JSON-safe, no f-string `{}` clash).
mtime-watched so editing a .tmpl on disk applies on the next request without
server restart.

Usage:
    from prompts import render
    text = render("fast_panda", DOMAIN="GALAXY", PERIOD="...", ...)
"""
from __future__ import annotations

import threading
from pathlib import Path
from string import Template
from typing import Any

_DIR = Path(__file__).parent
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, Template]] = {}  # name → (mtime, compiled)


def _load(name: str) -> Template:
    path = _DIR / f"{name}.tmpl"
    mtime = path.stat().st_mtime
    cached = _CACHE.get(name)
    if cached and cached[0] == mtime:
        return cached[1]
    with _LOCK:
        cached = _CACHE.get(name)
        if cached and cached[0] == mtime:
            return cached[1]
        tmpl = Template(path.read_text())
        _CACHE[name] = (mtime, tmpl)
        return tmpl


def render(name: str, **kwargs: Any) -> str:
    """Render prompt with $VAR substitution. Missing var → KeyError."""
    return _load(name).substitute(**kwargs)
