"""Query writer — LLM-facing wrapper over `data_sources/bq.py`.

Purpose: expose BQ fetchers to Claude as named tools, with the schema
catalog and usage hints needed for the model to pick the right one.

Boundary:
- This module knows what BQ tables exist and what each fetcher returns.
- It does NOT calculate KPIs (that's `kpi_calc.py`).
- It does NOT execute raw user-supplied SQL (use `data_sources.bq.estimate_cost`
  + `_run_query` directly if that capability is added later, guarded by a
  cost ceiling).

Wiring (deferred to caller):
- `describe_capabilities()` is meant to be injected into the mocha system
  prompt so the LLM knows the available fetchers.
- `dispatch(name, **kwargs)` is the single entry point that Claude calls
  via the agent SDK's tool interface.
"""
from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from data_sources import archive, bq


# ── BQ table catalog ───────────────────────────────────────────────────
# Compiled from datahub `search` results + remy-worker `remy/ds/bq/*.py`
# references. Keep in sync when fetchers added/changed.
TABLES: dict[str, dict[str, Any]] = {
    "gretel.frograms_us.ratings": {
        "description": "Galaxy/WatchaPedia user ratings (1-10 integer; UI 0.5~5.0 ★ × 2).",
        "domain": "GALAXY",
        "key_columns": ["user_id", "target_id", "target_type", "value", "updated_at"],
        "size_gb": 42,
        "partition": None,
        "load_pattern": "daily truncate-overwrite snapshot",
        "use_for": "RATE:GALAXY events, rating distribution, top-rated content",
        "caveats": "Deletions not captured (snapshot semantics). Person/ShortSeason rows ignored downstream.",
    },
    "gretel.frograms_us.wishes": {
        "description": "Galaxy/WatchaPedia wish list (보고싶어요).",
        "domain": "GALAXY",
        "key_columns": ["user_id", "target_id", "target_type", "updated_at"],
        "partition": None,
        "load_pattern": "daily truncate-overwrite snapshot",
        "use_for": "WISH:GALAXY events",
    },
    "gretel.frograms_us.comments": {
        "description": "Galaxy/WatchaPedia comments. Not yet wrapped by a fetcher.",
        "domain": "GALAXY",
        "use_for": "(future) comment-volume KPI",
    },
    "gretel.frograms_us.mehs": {
        "description": "Cross-platform 'meh' (관심없어요) reactions — Galaxy/Mars/Venus combined (single RDS table, no service partition).",
        "domain": "GALAXY + MARS + ALL (target_type 1=Movie, 2=TvSeason, 4=Book, 8=Webtoon, 256=ShortSeason)",
        "key_columns": ["id", "user_id", "target_id", "target_type", "created_at", "updated_at"],
        "size_mb": 741,
        "partition": None,
        "load_pattern": "daily truncate-overwrite snapshot (22:00 UTC)",
        "use_for": "MEH negative-signal KPI. Mirrored to archive `/archive/tutorial/mehs.ftr` — use `archive_mehs` fetcher (free) instead of BQ.",
        "caveats": "MEH ↔ WISH mutually exclusive at RDS (MEH 등록 시 동일 콘텐츠 WISH 자동 삭제). Snapshot semantics — deletions not captured.",
    },
    "gretel.production_us.mars_play_log_video": {
        "description": "Mars video play log (Hermes real-time pipeline).",
        "domain": "MARS + ADULT (filter on content_type)",
        "key_columns": ["user_id", "content_id", "content_type", "timestamp", "action", "from", "to"],
        "size_tb": 22,
        "partition": "timestamp (DAY)",
        "load_pattern": "streaming append",
        "use_for": "PLAY:MARS, PLAY:ADULT — filter action='play' to drop ping heartbeats",
        "warning": "Partition filter on `timestamp` is REQUIRED — full scan = ~$137 (22 TB).",
    },
    "gretel.production_us.mars_play_log_webtoon": {
        "description": "Mars webtoon play log. Not yet wrapped.",
        "domain": "MARS",
        "partition": "timestamp (DAY)",
    },
    "gretel.production_us.remy_rating": {
        "description": "Remy recommender rating log (Hermes real-time) — predicted + actual.",
        "domain": "MARS + GALAXY (cross-service)",
        "key_columns": ["user_id", "content_id", "content_type", "rating", "predicted_rating", "timestamp"],
        "size_gb": 19,
        "partition": "timestamp (DAY)",
        "use_for": "(future) recommendation-quality KPI; alternative source for fresh rating signals",
    },
    "gretel.data_us.mars_play_log_video_summary": {
        "description": "Pre-aggregated daily summary of mars_play_log_video. Cheap to query.",
        "domain": "MARS",
        "use_for": "(future) low-cost path for Mars daily KPI",
    },
}


# ── Fetcher registry ───────────────────────────────────────────────────
# Name → metadata. `fn` is the executable from data_sources.bq.
FETCHERS: dict[str, dict[str, Any]] = {
    "galaxy_ratings": {
        "fn": bq.fetch_galaxy_ratings,
        "signature": "(start: date, end: date) -> DataFrame",
        "returns": "user_id, content, created_at, action_type='RATE:GALAXY', value",
        "table": "gretel.frograms_us.ratings",
        "use_for": "Per-user, per-content Galaxy ratings in [start, end] window (KST date on updated_at).",
    },
    "galaxy_wishes": {
        "fn": bq.fetch_galaxy_wishes,
        "signature": "(start: date, end: date) -> DataFrame",
        "returns": "user_id, content, created_at, action_type='WISH:GALAXY'",
        "table": "gretel.frograms_us.wishes",
        "use_for": "Per-user, per-content Galaxy wishes in [start, end] window.",
    },
    "mars_plays": {
        "fn": bq.fetch_mars_plays,
        "signature": "(start: date, end: date) -> DataFrame",
        "returns": "user_id, content, created_at, action_type='PLAY:MARS', total_view_time",
        "table": "gretel.production_us.mars_play_log_video",
        "use_for": "Mars (왓챠) video play events. Excludes adult content. Drops 'ping' heartbeats.",
    },
    "adult_plays": {
        "fn": bq.fetch_adult_plays,
        "signature": "(start: date, end: date) -> DataFrame",
        "returns": "user_id, content, created_at, action_type='PLAY:ADULT', total_view_time",
        "table": "gretel.production_us.mars_play_log_video",
        "use_for": "Adult (성인+) video play events. Same table as mars_plays, filtered to AdultMovie.",
    },
    # ── Archive fetchers (free, read from /archive NFS) ─────────────────
    "archive_mehs": {
        "fn": archive.read_mehs,
        "signature": "(start: date, end: date) -> DataFrame",
        "returns": "user_id, content, content_type, action_type='MEH', created_at",
        "table": "/archive/tutorial/mehs.ftr (mirror of gretel.frograms_us.mehs)",
        "use_for": (
            "MEH (관심없음 / 별로에요) events — any service. Cross-platform single archive file; "
            "filter on `content_type` to scope by target type (1=Movie, 2=TvSeason, 4=Book, 8=Webtoon, 256=ShortSeason). "
            "No service field — MEH is platform-agnostic in RDS. Use this instead of BQ for MEH KPIs (free)."
        ),
    },
}


def list_fetchers() -> list[str]:
    """Return registered fetcher names (stable order)."""
    return sorted(FETCHERS)


def dispatch(fetcher_name: str, **kwargs: Any) -> pd.DataFrame:
    """Run a registered fetcher by name.

    This is the single entry point the LLM agent calls. Unknown names raise
    `ValueError` rather than silently no-op'ing.
    """
    if fetcher_name not in FETCHERS:
        raise ValueError(
            f"Unknown fetcher: {fetcher_name!r}. Known: {list_fetchers()}"
        )
    fn: Callable[..., pd.DataFrame] = FETCHERS[fetcher_name]["fn"]
    return fn(**kwargs)


def describe_capabilities() -> str:
    """Return a markdown blurb listing fetchers — for system prompt injection.

    The model uses this to decide which fetcher to call for a user question.
    Kept minimal: name, signature, what it returns, what to use it for.
    """
    lines = [
        "## Data fetchers (call via `dispatch('<name>', start=..., end=...)`)",
        "",
        "All fetchers return pandas DataFrames using the mocha event schema:",
        "`user_id`, `content` (`'{type_int}:{id}'`), `created_at` (unix sec), `action_type`, plus action-specific columns.",
        "",
        "Fetcher names prefixed with `archive_` read from `/archive/*` feather snapshots (free).",
        "Others hit BigQuery — partition filters and cost ceilings apply.",
        "",
    ]
    for name in list_fetchers():
        meta = FETCHERS[name]
        lines.append(f"### `{name}` {meta['signature']}")
        lines.append(f"- returns: {meta['returns']}")
        lines.append(f"- source: `{meta['table']}`")
        if meta.get("use_for"):
            lines.append(f"- when to use: {meta['use_for']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def describe_tables() -> str:
    """Return a markdown blurb of the underlying BQ table catalog.

    Optional companion to `describe_capabilities()`. The model may need
    this when composing a custom query that no fetcher covers yet.
    """
    lines = ["## BigQuery table catalog", ""]
    for fq_name, meta in TABLES.items():
        lines.append(f"### `{fq_name}`")
        lines.append(f"- {meta.get('description', '')}")
        if meta.get("domain"):
            lines.append(f"- domain: {meta['domain']}")
        if meta.get("partition"):
            lines.append(f"- partition: {meta['partition']}")
        if meta.get("use_for"):
            lines.append(f"- use for: {meta['use_for']}")
        if meta.get("warning"):
            lines.append(f"- ⚠️ {meta['warning']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "TABLES",
    "FETCHERS",
    "list_fetchers",
    "dispatch",
    "describe_capabilities",
    "describe_tables",
]
