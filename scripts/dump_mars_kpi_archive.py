#!/usr/bin/env python3
"""Mars rec KPI 1년치 BQ → archive feather dump.

수동 1회 실행 후 mocha 사이트는 archive 의 feather 파일들에서 즉시 데이터 조회
가능 (BQ scan 없음 → ~30s → ~1-2s, $0/day).

dependencies: pandas, pyarrow, google-cloud-bigquery, db-dtypes

pip install pandas pyarrow google-cloud-bigquery db-dtypes
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ImportError:
    sys.exit("ERROR: pandas 가 필요합니다. `pip install pandas pyarrow` 실행 후 재시도.")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dump_mars_kpi")

# ─────────────────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────────────────

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ai-develop-platform")
BQ_MAX_BYTES = int(os.environ.get("BQ_MAX_BYTES_BILLED",
                                  120 * 1024 ** 3))  # 120GB / chunk 안전 상한

KST = timezone(timedelta(hours=9))

# table_kind 카탈로그 — mocha 의 data_sources.bq.MARS_KPI_TABLES 와 동일.
# (table_name, has_purchase_count)
MARS_KPI_TABLES = {
    "svod":           ("remy_mars_kpi_stats", False),
    "tvod_all":       ("remy_mars_kpi_tod_stats", True),
    "tvod_adultplus": ("remy_mars_kpi_tod_adultplus_stats", True),
}

# 한 BQ chunk 길이 — 31일 (월별). 1주 svod ≈ 8GB, 31일 ≈ 35GB << 120GB 상한.
CHUNK_DAYS = 31


# ─────────────────────────────────────────────────────────────────────────
# Archive root 자동 해석 (mocha data_sources._archive_root 와 동일 로직)
# ─────────────────────────────────────────────────────────────────────────

def resolve_archive_root() -> Path:
    """ARCHIVE_DIR env → marker 후보 → fallback 순으로 archive root 해석."""
    env = os.environ.get("ARCHIVE_DIR")
    if env:
        return Path(env)
    for candidate in (Path("/archive"), Path("/mnt/ml-archive")):
        if candidate.exists() and any(
            (candidate / sub).exists()
            for sub in ("rec_galaxy", "rec_adult", "tutorial", "mocha")
        ):
            return candidate
    return Path("/mnt/ml-archive")


# ─────────────────────────────────────────────────────────────────────────
# BQ client (lazy)
# ─────────────────────────────────────────────────────────────────────────

_client = None


def _bq_client():
    global _client
    if _client is None:
        try:
            from google.cloud import bigquery
        except ImportError:
            sys.exit("ERROR: google-cloud-bigquery 가 필요합니다. "
                     "`pip install google-cloud-bigquery db-dtypes` 후 재시도.")
        _client = bigquery.Client(project=BQ_PROJECT)
        log.info("[bq] client init: project=%s", BQ_PROJECT)
    return _client


def _to_params(d: dict[str, Any]):
    from google.cloud import bigquery
    out = []
    for k, v in d.items():
        if isinstance(v, date):
            out.append(bigquery.ScalarQueryParameter(k, "DATE", v))
        elif isinstance(v, int):
            out.append(bigquery.ScalarQueryParameter(k, "INT64", v))
        elif isinstance(v, str):
            out.append(bigquery.ScalarQueryParameter(k, "STRING", v))
        else:
            raise TypeError(f"unsupported BQ param: {k}={type(v)}")
    return out


def _run_query(sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    from google.cloud import bigquery
    client = _bq_client()
    job_config = bigquery.QueryJobConfig(
        query_parameters=_to_params(params or {}),
        maximum_bytes_billed=BQ_MAX_BYTES,
    )
    job = client.query(sql, job_config=job_config)
    df = job.to_dataframe()
    log.info("[bq] %d rows, scanned %.2f GB, job=%s",
             len(df), (job.total_bytes_processed or 0) / 1024 ** 3, job.job_id)
    return df


# ─────────────────────────────────────────────────────────────────────────
# Fetchers (mocha data_sources.bq 와 동일 SQL)
# ─────────────────────────────────────────────────────────────────────────

def fetch_cs(start: date, end: date, table_kind: str) -> pd.DataFrame:
    table, has_purchase = MARS_KPI_TABLES[table_kind]
    purchase_sel = ("SUM(c.purchase_count) AS purchased"
                    if has_purchase else "0 AS purchased")
    sql = f"""
        SELECT
            remy_date,
            c.content AS content,
            c.title AS title,
            SUM(c.served_count)  AS served,
            SUM(c.exposed_count) AS exposed,
            SUM(c.click_count)   AS clicked,
            SUM(c.play_count)    AS played,
            SUM(c.wish_count)    AS wished,
            SUM(c.meh_count)     AS meh,
            {purchase_sel}
        FROM `gretel.production_us.{table}`, UNNEST(cs) AS c
        WHERE remy_date BETWEEN @start AND @end AND c.content IS NOT NULL
        GROUP BY remy_date, c.content, c.title
    """
    return _run_query(sql, {"start": start, "end": end})


def fetch_rs(start: date, end: date, table_kind: str) -> pd.DataFrame:
    table, _ = MARS_KPI_TABLES[table_kind]
    sql = f"""
        SELECT
            remy_date,
            r.key AS key,
            COUNT(*)                                       AS rs_served,
            COUNTIF(r.exposed_count > 0)                   AS rs_exposed,
            COUNTIF(r.click_count > 0)                     AS rs_clicked,
            SUM(ARRAY_LENGTH(r.click_cell_indexes))        AS rs_action_cells
        FROM `gretel.production_us.{table}`, UNNEST(rs) AS r
        WHERE remy_date BETWEEN @start AND @end
        GROUP BY remy_date, r.key
    """
    return _run_query(sql, {"start": start, "end": end})


def fetch_users(start: date, end: date, table_kind: str) -> pd.DataFrame:
    table, _ = MARS_KPI_TABLES[table_kind]
    sql = f"""
        SELECT remy_date,
               COUNT(DISTINCT user_id) AS unique_users,
               COUNT(*)                AS total_recommends
        FROM `gretel.production_us.{table}`
        WHERE remy_date BETWEEN @start AND @end
        GROUP BY remy_date
    """
    return _run_query(sql, {"start": start, "end": end})


def fetch_meta(start: date, end: date, table_kind: str) -> pd.DataFrame:
    """meta 는 윈도우 전체 1행 반환. dump 시 일별 호출."""
    table, _ = MARS_KPI_TABLES[table_kind]
    sql = f"""
        SELECT COUNT(*) AS total_recommends,
               COUNT(DISTINCT user_id) AS unique_users,
               APPROX_QUANTILES(elapsed, 100)[OFFSET(50)] AS elapsed_median_ms
        FROM `gretel.production_us.{table}`
        WHERE remy_date BETWEEN @start AND @end
    """
    return _run_query(sql, {"start": start, "end": end})


FETCHERS = {"cs": fetch_cs, "rs": fetch_rs,
            "users": fetch_users, "meta": fetch_meta}

# ─────────────────────────────────────────────────────────────────────────
# Dump 로직
# ─────────────────────────────────────────────────────────────────────────

def _date_to_fname(d) -> str:
    if hasattr(d, "strftime"):
        return d.strftime("%Y%m%d") + ".ftr"
    return pd.to_datetime(d).strftime("%Y%m%d") + ".ftr"


def _save_daily_split(df: pd.DataFrame, out_dir: Path, overwrite: bool) -> int:
    if df.empty or "remy_date" not in df.columns:
        return 0
    saved = 0
    for day, g in df.groupby("remy_date"):
        out_path = out_dir / _date_to_fname(day)
        if out_path.exists() and not overwrite:
            continue
        g.drop(columns=["remy_date"]).reset_index(drop=True).to_feather(out_path)
        saved += 1
    return saved


def dump_one(table_kind: str, kind: str, start: date, end: date,
             overwrite: bool, archive_root: Path) -> None:
    out_dir = archive_root / "mocha" / "mars_kpi" / table_kind / kind
    out_dir.mkdir(parents=True, exist_ok=True)
    fetcher = FETCHERS[kind]

    if kind == "meta":
        # meta 는 윈도우 전체 1행이라 일별 fetch
        current = start
        saved = 0
        while current <= end:
            out_path = out_dir / _date_to_fname(current)
            if out_path.exists() and not overwrite:
                current += timedelta(days=1)
                continue
            try:
                df = fetcher(current, current, table_kind)
                if not df.empty:
                    df.reset_index(drop=True).to_feather(out_path)
                    saved += 1
            except Exception as exc:
                log.error("[%s/%s/%s] %s", table_kind, kind, current, exc)
            current += timedelta(days=1)
        log.info("[%s/%s] → %d daily files", table_kind, kind, saved)
        return

    # cs/rs/users 는 월별 chunk → 일별 split
    chunk_start = start
    total_rows = total_saved = 0
    while chunk_start <= end:
        chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS - 1), end)
        t0 = time.time()
        try:
            df = fetcher(chunk_start, chunk_end, table_kind)
        except Exception as exc:
            log.error("[%s/%s] chunk %s~%s: %s",
                      table_kind, kind, chunk_start, chunk_end, exc)
            chunk_start = chunk_end + timedelta(days=1)
            continue
        saved = _save_daily_split(df, out_dir, overwrite)
        total_rows += len(df)
        total_saved += saved
        log.info("[%s/%s] %s~%s: %d rows, %d files (%.1fs)",
                 table_kind, kind, chunk_start, chunk_end,
                 len(df), saved, time.time() - t0)
        chunk_start = chunk_end + timedelta(days=1)
    log.info("[%s/%s] TOTAL: %d rows, %d daily files",
             table_kind, kind, total_rows, total_saved)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Mars rec KPI 1년치 BQ → archive feather dump",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n예시:\n"
               "  # 1년치 한번에 (~$10, ~30분):\n"
               "  python3 dump_mars_kpi_archive.py\n\n"
               "  # 어제치만 ($0.03, 1분):\n"
               "  python3 dump_mars_kpi_archive.py --days 1\n\n"
               "  # SVOD 만 1주:\n"
               "  python3 dump_mars_kpi_archive.py --tables svod --days 7\n",
    )
    p.add_argument("--start", help="YYYY-MM-DD, default = end-364")
    p.add_argument("--end", help="YYYY-MM-DD, default = 어제 KST")
    p.add_argument("--days", type=int, help="end 부터 N일 전까지")
    p.add_argument("--tables", nargs="+", choices=list(MARS_KPI_TABLES.keys()),
                   default=list(MARS_KPI_TABLES.keys()))
    p.add_argument("--kinds", nargs="+", choices=list(FETCHERS.keys()),
                   default=list(FETCHERS.keys()))
    p.add_argument("--overwrite", action="store_true",
                   help="기존 feather 파일 덮어쓰기")
    args = p.parse_args()

    today = datetime.now(KST).date()
    end = date.fromisoformat(args.end) if args.end else today - timedelta(days=1)
    if args.start and args.days:
        p.error("--start 와 --days 동시 사용 불가")
    start = (date.fromisoformat(args.start) if args.start
             else end - timedelta(days=(args.days or 365) - 1))
    if start > end:
        p.error(f"start({start}) > end({end})")

    archive_root = resolve_archive_root()
    log.info("=== Mars rec KPI archive dump ===")
    log.info("  archive root: %s", archive_root)
    log.info("  output: %s/mocha/mars_kpi/", archive_root)
    log.info("  window: %s ~ %s (%d days)", start, end, (end - start).days + 1)
    log.info("  tables: %s", args.tables)
    log.info("  kinds:  %s", args.kinds)
    log.info("  overwrite: %s", args.overwrite)

    out_test = archive_root / "mocha" / "mars_kpi"
    out_test.mkdir(parents=True, exist_ok=True)
    test_file = out_test / ".write_test"
    try:
        test_file.write_text("ok")
        test_file.unlink()
    except Exception as exc:
        sys.exit(f"ERROR: archive write 실패 — {exc}\n"
                 f"  target: {out_test}\n"
                 f"  ARCHIVE_DIR env 또는 권한 확인.")

    t_global = time.time()
    for tk in args.tables:
        for kind in args.kinds:
            dump_one(tk, kind, start, end, args.overwrite, archive_root)
    log.info("=== Done in %.1fs ===", time.time() - t_global)
    return 0


if __name__ == "__main__":
    sys.exit(main())
