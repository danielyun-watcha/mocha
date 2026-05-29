"""BigQuery fetchers for mocha KPI dashboard.

Each fetcher returns a pandas DataFrame in the mocha event schema:

- `user_id` (int64)
- `content` (str, "{content_type_int}:{content_id}")
- `created_at` (int, unix seconds)
- `action_type` (str, "{ACTION}:{DOMAIN}" — e.g. "RATE:GALAXY", "PLAY:MARS")
- value-bearing column for the action (e.g. `value` for RATE, `total_view_time`
  for PLAY)

Downstream `kpi_calc.py` processors expect exactly this shape.

Cost discipline (CLAUDE.md §BigQuery 쿼리 규칙):
- No `SELECT *`, only listed columns
- Mandatory partition / date filter on every query
- `LIMIT` defaulted on exploratory paths
- `dry_run` available via `estimate_cost`
- `BQ_PROJECT` env override; default `ai-develop-platform` (ADP standard)

Authentication: in the ADP pod, IRSA/WIF auto-injects GCP credentials
(`GOOGLE_APPLICATION_CREDENTIALS=/etc/gcp/gcp-wif-config.json`); the
`bigquery.Client` picks them up via ADC chain — no key handling in code.

Reference: remy-worker `remy/ds/bq/{user,content}.py` for query patterns.
This module is a slimmer, mocha-shaped reimplementation; we do NOT import
remy at runtime.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from typing import Any

import pandas as pd

log = logging.getLogger("mocha.bq")

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ai-develop-platform")

# Content type integer codes — must match mocha's existing `content` string
# convention used in archive feather files. Verified against
# kpi.py:_top_genres which expects {1: movie, 2: tv_season, 4: book, 8: webtoon}.
CONTENT_TYPE_CODE = {
    "Movie": 1,
    "TvSeason": 2,
    "Book": 4,
    "Webtoon": 8,
    "AdultMovie": 16,
    "AdultWebtoon": 32,
    "ShortEpisode": 64,
    "TvEpisode": 128,
}

_client = None


def _get_client():
    """Lazy BQ client — imports google-cloud-bigquery on first call."""
    global _client
    if _client is None:
        from google.cloud import bigquery  # noqa: WPS433 — intentional lazy
        _client = bigquery.Client(project=BQ_PROJECT)
        log.info("[bq] client initialised for project=%s", BQ_PROJECT)
    return _client


def _run_query(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Execute query with parameterised inputs, return DataFrame."""
    from google.cloud import bigquery  # lazy

    client = _get_client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=_to_bq_params(params or {}),
    )
    job = client.query(sql, job_config=job_config)
    df = job.to_dataframe()
    log.info(
        "[bq] query done — rows=%d scanned=%s bytes job_id=%s",
        len(df), f"{job.total_bytes_processed:,}", job.job_id,
    )
    return df


def _to_bq_params(d: dict[str, Any]):
    """Convert {name: value} → list[bigquery.ScalarQueryParameter] inferring type."""
    from google.cloud import bigquery  # lazy

    out = []
    for k, v in d.items():
        if isinstance(v, date):
            out.append(bigquery.ScalarQueryParameter(k, "DATE", v))
        elif isinstance(v, int):
            out.append(bigquery.ScalarQueryParameter(k, "INT64", v))
        elif isinstance(v, float):
            out.append(bigquery.ScalarQueryParameter(k, "FLOAT64", v))
        elif isinstance(v, str):
            out.append(bigquery.ScalarQueryParameter(k, "STRING", v))
        else:
            raise TypeError(f"Unsupported BQ parameter type for {k}: {type(v)}")
    return out


def estimate_cost(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Dry-run a query and return scanned bytes + USD cost estimate.

    Use this before running expensive queries to surface partition-misses
    or accidental full scans.
    """
    from google.cloud import bigquery  # lazy

    client = _get_client()
    job_config = bigquery.QueryJobConfig(
        dry_run=True,
        use_query_cache=False,
        query_parameters=_to_bq_params(params or {}),
    )
    job = client.query(sql, job_config=job_config)
    scanned = job.total_bytes_processed or 0
    return {
        "bytes": scanned,
        "gb": round(scanned / (1024 ** 3), 3),
        "tb": round(scanned / (1024 ** 4), 6),
        "usd": round((scanned / (1024 ** 4)) * 6.25, 4),  # $6.25 per TB on-demand
    }


# ── Galaxy / WatchaPedia ────────────────────────────────────────────────
def fetch_galaxy_ratings(start: date, end: date) -> pd.DataFrame:
    """RATE events from `gretel.frograms_us.ratings` (Galaxy / WatchaPedia).

    The source is a daily truncate-overwrite snapshot of the RDS `ratings`
    table — newly created or updated ratings in the window are captured by
    filtering on `updated_at`. Deleted ratings are NOT captured (snapshot
    semantics).

    Output columns:
      - user_id (int)
      - content (str, "{1|2|4|8}:{target_id}")
      - created_at (int, unix sec) — derived from updated_at (KST date filter)
      - action_type (str, "RATE:GALAXY")
      - value (int, 1-10 — UI 0.5-5.0 ★ × 2)

    Cost note: this table has no partition; the query scans full snapshot
    (~42 GB once). Output is filtered to Movie/TvSeason/Book/Webtoon only;
    Person and ShortSeason are skipped (rare and out of mocha scope).
    """
    sql = """
        SELECT
            user_id,
            CASE target_type
                WHEN 'Movie' THEN CONCAT('1:', CAST(target_id AS STRING))
                WHEN 'TvSeason' THEN CONCAT('2:', CAST(target_id AS STRING))
                WHEN 'Book' THEN CONCAT('4:', CAST(target_id AS STRING))
                WHEN 'Webtoon' THEN CONCAT('8:', CAST(target_id AS STRING))
            END AS content,
            UNIX_SECONDS(updated_at) AS created_at,
            'RATE:GALAXY' AS action_type,
            value
        FROM `gretel.frograms_us.ratings`
        WHERE DATE(updated_at, 'Asia/Seoul') BETWEEN @start AND @end
          AND target_type IN ('Movie', 'TvSeason', 'Book', 'Webtoon')
          AND value BETWEEN 1 AND 10
    """
    return _run_query(sql, {"start": start, "end": end})


def fetch_galaxy_wishes(start: date, end: date) -> pd.DataFrame:
    """WISH events from `gretel.frograms_us.wishes` (Galaxy).

    Same snapshot semantics as ratings. Output:
      - user_id, content, created_at, action_type='WISH:GALAXY'
    """
    sql = """
        SELECT
            user_id,
            CASE target_type
                WHEN 'Movie' THEN CONCAT('1:', CAST(target_id AS STRING))
                WHEN 'TvSeason' THEN CONCAT('2:', CAST(target_id AS STRING))
                WHEN 'Book' THEN CONCAT('4:', CAST(target_id AS STRING))
                WHEN 'Webtoon' THEN CONCAT('8:', CAST(target_id AS STRING))
            END AS content,
            UNIX_SECONDS(updated_at) AS created_at,
            'WISH:GALAXY' AS action_type
        FROM `gretel.frograms_us.wishes`
        WHERE DATE(updated_at, 'Asia/Seoul') BETWEEN @start AND @end
          AND target_type IN ('Movie', 'TvSeason', 'Book', 'Webtoon')
    """
    return _run_query(sql, {"start": start, "end": end})


# ── Mars / Watcha ───────────────────────────────────────────────────────
def fetch_mars_plays(start: date, end: date) -> pd.DataFrame:
    """PLAY events from `gretel.production_us.mars_play_log_video` (Mars).

    Partition: DAY on `timestamp` — the `@start`/`@end` filter is REQUIRED
    for cost (table is ~22 TB, 18 GB/day). Excludes adult content
    (`content_type = 'AdultMovie'`); use `fetch_adult_plays` for that.

    Filters on `action = 'play'` to drop `ping` heartbeats (otherwise the
    output would double-count playback duration).

    Output columns:
      - user_id, content, created_at, action_type='PLAY:MARS'
      - total_view_time (int, seconds, `to - from`)
    """
    sql = """
        SELECT
            user_id,
            CASE content_type
                WHEN 'Movie' THEN CONCAT('1:', CAST(content_id AS STRING))
                WHEN 'TvEpisode' THEN CONCAT('128:', CAST(content_id AS STRING))
                WHEN 'ShortEpisode' THEN CONCAT('64:', CAST(content_id AS STRING))
            END AS content,
            UNIX_SECONDS(`timestamp`) AS created_at,
            'PLAY:MARS' AS action_type,
            GREATEST(`to` - `from`, 0) AS total_view_time
        FROM `gretel.production_us.mars_play_log_video`
        WHERE DATE(`timestamp`, 'Asia/Seoul') BETWEEN @start AND @end
          AND action = 'play'
          AND content_type IN ('Movie', 'TvEpisode', 'ShortEpisode')
          AND user_id IS NOT NULL
    """
    return _run_query(sql, {"start": start, "end": end})


# ── Adult / 성인+ ───────────────────────────────────────────────────────
def fetch_adult_plays(start: date, end: date) -> pd.DataFrame:
    """PLAY events for adult content from `gretel.production_us.mars_play_log_video`.

    Same table as `fetch_mars_plays`, filtered on `content_type = 'AdultMovie'`.
    Adult webtoons live in a different table; this only covers video.

    Output: user_id, content, created_at, action_type='PLAY:ADULT', total_view_time
    """
    sql = """
        SELECT
            user_id,
            CONCAT('16:', CAST(content_id AS STRING)) AS content,
            UNIX_SECONDS(`timestamp`) AS created_at,
            'PLAY:ADULT' AS action_type,
            GREATEST(`to` - `from`, 0) AS total_view_time
        FROM `gretel.production_us.mars_play_log_video`
        WHERE DATE(`timestamp`, 'Asia/Seoul') BETWEEN @start AND @end
          AND action = 'play'
          AND content_type = 'AdultMovie'
          AND user_id IS NOT NULL
    """
    return _run_query(sql, {"start": start, "end": end})


__all__ = [
    "BQ_PROJECT",
    "CONTENT_TYPE_CODE",
    "estimate_cost",
    "fetch_galaxy_ratings",
    "fetch_galaxy_wishes",
    "fetch_mars_plays",
    "fetch_adult_plays",
]
