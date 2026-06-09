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
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

from ._archive_root import _resolve_archive_root

log = logging.getLogger("mocha.archive")

KST = timezone(timedelta(hours=9))
ARCHIVE_DIR = _resolve_archive_root()

# ── mocha 전용 archive 폴더 (다른 사내 task 와 격리) ─────────────────────
MOCHA_ARCHIVE_DIR = ARCHIVE_DIR / "mocha"

# ── MEH (관심없음 / 별로에요) ─────────────────────────────────────────────
MEHS_PATH = MOCHA_ARCHIVE_DIR / "mehs.ftr"

# ── Mars TVOD 결제 (rentals + possessions + payment amount) ──────────────
MARS_TVOD_PURCHASES_PATH = MOCHA_ARCHIVE_DIR / "mars_tvod_purchases.ftr"


def _kst_window_unix(start: date, end: date) -> tuple[int, int]:
    """[start KST 00:00, end+1 KST 00:00) unix-second window."""
    start_ts = int(datetime.combine(start, time.min, tzinfo=KST).timestamp())
    end_ts = int(datetime.combine(end + timedelta(days=1), time.min, tzinfo=KST).timestamp())
    return start_ts, end_ts


def read_mehs(start: date, end: date) -> pd.DataFrame:
    """MEH events from `/archive/mocha/mehs.ftr` (full-history dump).

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


def read_mars_tvod_purchases(start: date, end: date) -> pd.DataFrame:
    """Mars TVOD 결제 events (`/archive/mocha/mars_tvod_purchases.ftr`).

    Source: BQ `pacific-350708.hudson_us.{rentals,possessions}` UNION
    + `hudson_us.payments` JOIN for amount_cents. Dumped 2026-05-29.

    Schema:
      - user_id (int)
      - content_type (int)  — 1=Movie / 2=TvSeason / 128=TvEpisode /
                              8=Webtoon / 16=AdultMovie / 32=AdultWebtoon
      - content (str, "{content_type}:{item_id}")
      - action_type (str, "rental" | "possession")
      - timestamp (int, unix sec — created_at)
      - amount_cents (int)  — 결제 금액. 단 한 payment 가 multiple item 묶을 수
                             있어서 sum 시 over-count 가능 (대부분 1:1)

    Note: AdultMovie/AdultWebtoon row 도 포함되나 adult 도메인 KPI 는
    `/archive/rec_adult/behavior_logs` 우선 사용 (그쪽 가격이 CONTENT_TO_PRICE.pkl
    기반 — 더 안정적). 이 파일에서 adult 는 cross-check 용도.
    """
    if not MARS_TVOD_PURCHASES_PATH.exists():
        raise FileNotFoundError(
            f"Mars TVOD archive not found at {MARS_TVOD_PURCHASES_PATH}."
        )
    df = pd.read_feather(MARS_TVOD_PURCHASES_PATH)
    start_ts, end_ts = _kst_window_unix(start, end)
    df = df[(df["timestamp"] >= start_ts) & (df["timestamp"] < end_ts)].copy()
    df = df.rename(columns={"timestamp": "created_at"})
    log.info("[archive] read_mars_tvod_purchases %s..%s → %d rows", start, end, len(df))
    return df[["user_id", "content", "content_type", "action_type",
               "created_at", "amount_cents"]]


__all__ = [
    "ARCHIVE_DIR",
    "MOCHA_ARCHIVE_DIR",
    "MEHS_PATH",
    "MARS_TVOD_PURCHASES_PATH",
    "read_mehs",
    "read_mars_tvod_purchases",
]
