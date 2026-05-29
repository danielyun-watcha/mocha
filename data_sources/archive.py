"""Archive (NFS feather) fetchers for mocha KPI dashboard.

Cumulative behavior_log snapshots produced by remy-worker prepare tasks live
under `ARCHIVE_DIR` (default `/mnt/ml-archive`, override via env). Each fetcher
returns a pandas DataFrame in the mocha event schema:

- `user_id` (int)
- `content` (str, "{content_type_int}:{content_id}")
- `created_at` (int, unix seconds)
- `action_type` (str — domain-specific label)
- value-bearing column where applicable

Fetchers are intentionally narrow: each one targets ONE file (or directory)
and one action family. Joining across domains / KPI rollups belongs in
`kpi_calc.py`.

Schema-level reference for `MEH` content_type 256 (ShortSeason) — assigned
2026-05-29; see project memory `reference_content_type_codes.md`.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger("mocha.archive")

KST = timezone(timedelta(hours=9))
ARCHIVE_DIR = Path(os.environ.get("ARCHIVE_DIR", "/mnt/ml-archive"))

# ── MEH (관심없음 / 별로에요) ─────────────────────────────────────────────
MEHS_PATH = ARCHIVE_DIR / "tutorial" / "mehs.ftr"


def _kst_window_unix(start: date, end: date) -> tuple[int, int]:
    """[start KST 00:00, end+1 KST 00:00) unix-second window."""
    start_ts = int(datetime.combine(start, time.min, tzinfo=KST).timestamp())
    end_ts = int(datetime.combine(end + timedelta(days=1), time.min, tzinfo=KST).timestamp())
    return start_ts, end_ts


def read_mehs(start: date, end: date) -> pd.DataFrame:
    """MEH events from `/archive/tutorial/mehs.ftr` (full-history dump).

    Source: BQ `gretel.frograms_us.mehs` daily snapshot, dumped 2026-05-29.
    Schema covers galaxy/mars/all services in a single file — `mehs` is a
    cross-platform RDS table without service-level partitioning.

    Window filter uses KST midnight boundaries on the `timestamp` column
    (which carries `created_at` unix seconds).

    Output columns:
      - user_id (int)
      - content (str, "{type_code}:{target_id}")
      - content_type (int)  — 1=Movie, 2=TvSeason, 4=Book, 8=Webtoon, 256=ShortSeason
      - action_type (str, "MEH")
      - created_at (int, unix sec)

    Note: MEH ↔ WISH are mutually exclusive at the RDS level (registering
    MEH auto-deletes the matching WISH). The archive snapshot is a point-in-
    time view; deletes are NOT captured.
    """
    if not MEHS_PATH.exists():
        raise FileNotFoundError(
            f"MEH archive not found at {MEHS_PATH}. "
            f"Re-run the dump or set ARCHIVE_DIR."
        )

    df = pd.read_feather(MEHS_PATH)
    start_ts, end_ts = _kst_window_unix(start, end)
    df = df[(df["timestamp"] >= start_ts) & (df["timestamp"] < end_ts)].copy()

    # Conform to mocha event schema: rename + relabel action_type
    df = df.rename(columns={"timestamp": "created_at"})
    df["action_type"] = "MEH"
    df = df.drop(columns=["value"], errors="ignore")  # MEH has no metric value

    log.info("[archive] read_mehs %s..%s → %d rows", start, end, len(df))
    return df[["user_id", "content", "content_type", "action_type", "created_at"]]


__all__ = [
    "ARCHIVE_DIR",
    "MEHS_PATH",
    "read_mehs",
]
