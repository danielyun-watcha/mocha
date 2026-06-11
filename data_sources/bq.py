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
    # 서버측 하드 비용 상한 — 초과 시 BQ 가 job 을 실패시킴(과금 X).
    # 기본 60GB: 비파티션 galaxy 스냅샷(~42GB) + 여유. override: BQ_MAX_BYTES_BILLED.
    # 오발사 full-scan 이 청구로 이어지는 것을 방지 (현재 dispatch 는 Phase 1 미연결이나
    # 향후 LLM 연결 시 가드로 작동).
    max_bytes = int(os.environ.get("BQ_MAX_BYTES_BILLED", 60 * 1024 ** 3))
    job_config = bigquery.QueryJobConfig(
        query_parameters=_to_bq_params(params or {}),
        maximum_bytes_billed=max_bytes,
    )
    job = client.query(sql, job_config=job_config)
    df = job.to_dataframe()
    log.info(
        "[bq] query done — rows=%d scanned=%s bytes job_id=%s",
        len(df), f"{job.total_bytes_processed or 0:,}", job.job_id,
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


# mars rec KPI 테이블 카탈로그 — 3개 모두 cs[]/rs[] schema 동일, 차이는 cs.purchase_count 유무
MARS_KPI_TABLES = {
    "svod":           ("remy_mars_kpi_stats", False),            # 구독 — purchase 없음
    "tvod_all":       ("remy_mars_kpi_tod_stats", True),         # TVOD 전체
    "tvod_adultplus": ("remy_mars_kpi_tod_adultplus_stats", True),
}


def _mars_table(kind: str) -> tuple[str, bool]:
    if kind not in MARS_KPI_TABLES:
        raise ValueError(f"unknown mars kpi table kind: {kind!r}")
    return MARS_KPI_TABLES[kind]


_ADULTPLUS_FILTER_KEYS = {"client", "country"}  # 추가 지원: subscribe, age_group


def _adultplus_where(filters: dict | None) -> tuple[str, dict]:
    """필터 dict → 추가 WHERE 절 + parameterized params.

    지원 필터 (PDF Datastudio 와 동일):
      - client: comma-separated client_type int (1=iOS, 2=Android, 3=Web)
      - country: comma-separated country_code (KR, JP, ...)
    그 외 키는 무시 (subscribe / age_group 매핑 미확정 → no-op).
    """
    if not filters:
        return "", {}
    fragments = []
    params: dict = {}
    raw_client = (filters.get("client") or "").strip()
    if raw_client:
        ints = []
        for v in raw_client.split(","):
            try:
                ints.append(int(v))
            except (ValueError, TypeError):
                pass
        if ints:
            placeholders = ", ".join(f"@_cli_{i}" for i, _ in enumerate(ints))
            fragments.append(f"client_type IN ({placeholders})")
            for i, v in enumerate(ints):
                params[f"_cli_{i}"] = v
    raw_country = (filters.get("country") or "").strip()
    if raw_country:
        codes = [c.strip() for c in raw_country.split(",") if c.strip()]
        if codes:
            placeholders = ", ".join(f"@_ctr_{i}" for i, _ in enumerate(codes))
            fragments.append(f"country_code IN ({placeholders})")
            for i, v in enumerate(codes):
                params[f"_ctr_{i}"] = v
    if not fragments:
        return "", {}
    return " AND " + " AND ".join(fragments), params


# ── Mars recommendation KPI (SVOD / TVOD all / TVOD AdultPlus) ──────────
def fetch_mars_kpi_tod_adultplus(start: date, end: date,
                                 filters: dict | None = None,
                                 table_kind: str = "tvod_adultplus") -> pd.DataFrame:
    """`remy_mars_kpi_tod_adultplus_stats` cs[] unnest — daily × content counts.

    Mars 본 서비스의 추천 슬롯에서 노출된 **AdultPlus** 콘텐츠의 funnel
    (served → exposed → clicked → wished/played/purchased). 독립 성인관
    (rec_adult) 과 다른 제품 데이터.

    Partition: DAY on `remy_date` (필수 filter — 풀스캔 방지).

    Output (date × content):
      - remy_date (date)
      - content (str), title (str)
      - served (int), exposed (int), clicked (int)
      - played (int), wished (int), meh (int), purchased (int)
    """
    table, has_purchase = _mars_table(table_kind)
    purchase_select = "SUM(c.purchase_count) AS purchased" if has_purchase else "0 AS purchased"
    where, fp = _adultplus_where(filters)
    sql = f"""
        SELECT
            remy_date,
            c.content AS content,
            c.title AS title,
            SUM(c.served_count) AS served,
            SUM(c.exposed_count) AS exposed,
            SUM(c.click_count) AS clicked,
            SUM(c.play_count) AS played,
            SUM(c.wish_count) AS wished,
            SUM(c.meh_count) AS meh,
            {purchase_select}
        FROM `gretel.production_us.{table}`,
        UNNEST(cs) AS c
        WHERE remy_date BETWEEN @start AND @end
          AND c.content IS NOT NULL
          {where}
        GROUP BY remy_date, c.content, c.title
    """
    return _run_query(sql, {"start": start, "end": end, **fp})


def fetch_mars_kpi_tod_adultplus_rs(start: date, end: date,
                                    filters: dict | None = None,
                                    table_kind: str = "tvod_adultplus") -> pd.DataFrame:
    """`rs[]` unnest — daily × row_key 추천 슬롯 stats.

    PDF 의 "Rows: exposed / Rows: clicked / Actions" pie + Exposed-Actioned
    timeseries 산출용.

    Output (date × key):
      - remy_date (date), key (str, e.g. titledRecommend / library / ...)
      - rs_exposed (int) — 슬롯 노출
      - rs_clicked (int) — 슬롯 클릭
      - rs_action_cells (int) — 클릭된 셀 수 합 (사용자가 클릭한 액션 total)
    """
    table, _ = _mars_table(table_kind)
    where, fp = _adultplus_where(filters)
    # PDF Row 테이블 정의:
    #   served  = row 가 응답에 포함된 횟수 (COUNT after UNNEST)
    #   exposed = exposure 가 1회 이상 일어난 row 수 (COUNTIF > 0) — 노출 빈도
    #   clicked = click 이 1회 이상 일어난 row 수 (COUNTIF > 0) — 클릭 빈도
    #   action_cells = 총 클릭된 셀 수 (SUM array_length) — 가중 action 지표
    # SUM(click_count) 은 row 당 셀 클릭 평균이 1 초과면 부풀어서 PDF 와 ~2x 차이.
    # COUNTIF 로 바꿔 PDF 정의 일치 (titledRecommend 25% click ratio 등 매치).
    # null key 도 보고 싶을 수 있어 IS NOT NULL 필터 제거.
    sql = f"""
        SELECT
            remy_date,
            r.key AS key,
            COUNT(*) AS rs_served,
            COUNTIF(r.exposed_count > 0) AS rs_exposed,
            COUNTIF(r.click_count > 0) AS rs_clicked,
            SUM(ARRAY_LENGTH(r.click_cell_indexes)) AS rs_action_cells
        FROM `gretel.production_us.{table}`,
        UNNEST(rs) AS r
        WHERE remy_date BETWEEN @start AND @end
          {where}
        GROUP BY remy_date, r.key
    """
    return _run_query(sql, {"start": start, "end": end, **fp})


def fetch_mars_kpi_tod_adultplus_users_daily(start: date, end: date,
                                             filters: dict | None = None,
                                             table_kind: str = "tvod_adultplus") -> pd.DataFrame:
    """일별 unique users / 추천 횟수 (PDF Users/Recommends timeseries).

    Output (date):
      - remy_date, unique_users, total_recommends
    """
    table, _ = _mars_table(table_kind)
    where, fp = _adultplus_where(filters)
    sql = f"""
        SELECT
            remy_date,
            COUNT(DISTINCT user_id) AS unique_users,
            COUNT(*) AS total_recommends
        FROM `gretel.production_us.{table}`
        WHERE remy_date BETWEEN @start AND @end
          {where}
        GROUP BY remy_date
    """
    return _run_query(sql, {"start": start, "end": end, **fp})


def fetch_mars_kpi_tod_adultplus_meta(start: date, end: date,
                                      filters: dict | None = None,
                                      table_kind: str = "tvod_adultplus") -> pd.DataFrame:
    """Session-level meta — recommends, unique users, elapsed median.

    Output (single row):
      - total_recommends (int) — base row count
      - unique_users (int)
      - elapsed_median_ms (float)
    """
    table, _ = _mars_table(table_kind)
    where, fp = _adultplus_where(filters)
    sql = f"""
        SELECT
            COUNT(*) AS total_recommends,
            COUNT(DISTINCT user_id) AS unique_users,
            APPROX_QUANTILES(elapsed, 100)[OFFSET(50)] AS elapsed_median_ms
        FROM `gretel.production_us.{table}`
        WHERE remy_date BETWEEN @start AND @end
          {where}
    """
    return _run_query(sql, {"start": start, "end": end, **fp})


__all__ = [
    "BQ_PROJECT",
    "CONTENT_TYPE_CODE",
    "estimate_cost",
    "fetch_galaxy_ratings",
    "fetch_galaxy_wishes",
    "fetch_mars_plays",
    "fetch_adult_plays",
    "fetch_mars_kpi_tod_adultplus",
    "fetch_mars_kpi_tod_adultplus_rs",
    "fetch_mars_kpi_tod_adultplus_users_daily",
    "fetch_mars_kpi_tod_adultplus_meta",
]
