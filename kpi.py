"""Phase 1 KPI dashboard backend.

Reads /archive/*/behavior_logs/*.ftr and aggregates per-domain daily KPIs.

Data sources (확정):
  GALAXY  /archive/rec_galaxy/behavior_logs/YYYYMMDD_YYYYMMDD.ftr
          cols: user_id / content_type / content / action_type (int 1/2/6/7) /
                value / timestamp
          actions: 1=RATE 2=WISH 6=SEARCH 7=CLICK

  MARS    /archive/user_bert/behavior_logs2/train/YYYYMMDD_YYYYMMDD.ftr
          cols: user_id / timestamp / action_type (str "CLICK:MARS" etc) /
                content / rating
          MARS actions: CLICK:MARS · PLAY:MARS · WISH:MARS · SEARCH:MARS · RATE:MARS
          (galaxy events 도 같은 파일에 섞여 있어서 :MARS 만 필터한다)

  ADULT   /archive/rec_adult/behavior_logs/YYYYMMDD_YYYYMMDD.ftr
          cols: user_id / content / timestamp / action_type (str) / response_id
          actions: click · preview · play · wish · rental · possession

File selection: 같은 end date 의 cover snapshot 여러 개 중 start 가 가장 작은
(=가장 긴 cover) 파일 1개만 읽는다.  중복 데이터 방지 + 가장 안정적인 base.
"""
from __future__ import annotations

import copy
import glob
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger("mocha.kpi")

KST = timezone(timedelta(hours=9))


# ── file read cache (preprocessed) ──────────────────────────────
# MARS monthly snapshots are 25M+ rows.  Cache the *normalized* form
# (string action_type without :MARS suffix, KST date column added)
# so KPI groupbys stay fast on repeat queries.  Key = (path, domain).
_CACHE: OrderedDict[tuple[str, str], tuple[float, pd.DataFrame]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
# 3 domains × (summary + series) × (7-day prewarm + 30-day long-prewarm) = 12
# 키 + dashboard 임의 기간 조합으로 ~20+. 작은 LRU 면 30일 캐시가 7일 prewarm 에
# 의해 evict 돼서 다음 요청 cold restart 됨. 30 으로 잡고 안정 hit 유지.
_CACHE_MAX = 30


def _cat_prefix_int(s: pd.Series) -> pd.Series:
    """content categorical("1:xxx") → content_type int(1).

    category 라벨에서 한 번만 prefix 파싱 후 codes 로 broadcast — 행 수와 무관하게
    O(n_categories). 52M행 `.astype(str).str.split` (수 초) 대비 수십 ms."""
    cats = s.cat.categories
    prefix = cats.str.split(":").str[0].astype("int64").to_numpy()
    codes = s.cat.codes.to_numpy()
    return pd.Series(prefix[codes], index=s.index)


def _preprocess(df: pd.DataFrame, domain: str) -> pd.DataFrame:
    """Normalize action_type strings and pre-compute KST 'date' column.

    Runs once per file (in cache).  Keeps subsequent KPI queries cheap.

    Perf: action_type/content 는 categorical 이므로 `.astype(str)` 로 전체 행을
    문자열화하지 않는다. category 라벨 단위 연산(few categories) + codes broadcast
    로 처리 — mars 월별 파일(52M행) 기준 ~9s → ~0.3s."""
    if domain == "mars" and "action_type" in df.columns:
        # category 라벨 중 ":MARS" 로 끝나는 것만 골라 isin (행 단위 astype 회피).
        # galaxy 이벤트가 같은 파일에 섞여 있어 :MARS 만 남긴다.
        cats = df["action_type"].cat.categories
        mars_cats = [c for c in cats if str(c).endswith(":MARS")]
        df = df[df["action_type"].isin(mars_cats)].copy()
        # ":MARS" suffix 제거 — category 라벨 rename (행 아닌 라벨 단위).
        df["action_type"] = (
            df["action_type"].cat.remove_unused_categories()
            .cat.rename_categories(lambda c: str(c).split(":")[0])
        )
        # content_type ("1:xxx" → 1) — category prefix broadcast.
        df["content_type"] = _cat_prefix_int(df["content"])
    elif domain == "galaxy" and "action_type" in df.columns:
        mapping = {1: "RATE", 2: "WISH", 6: "SEARCH", 7: "CLICK"}
        df = df.copy()
        df["action_type"] = (
            df["action_type"].astype(int).map(mapping).fillna("OTHER")
            .astype("category")
        )
    elif domain == "adult" and "action_type" in df.columns:
        df = df.copy()
        df["action_type"] = df["action_type"].astype(str).str.upper().astype("category")
    # Pre-compute KST date string (used for daily groupby).
    df["date"] = _kst_date_fast(df["timestamp"])
    return df


def _kst_date_fast(ts: pd.Series) -> pd.Series:
    """unix-sec Series → KST "YYYY-MM-DD" string Series.

    `.dt.date.astype(str)` 는 행마다 python date 객체+문자열 생성(33M행 ~25s).
    대신 (1) +9h 후 day 번호(int)로 floor, (2) 고유 day(1년=365개)만 문자열화,
    (3) codes broadcast → 행 수 무관 수십 ms."""
    import numpy as np
    day = ((ts.to_numpy().astype("int64") + 32400) // 86400)  # KST day number
    uniq, inv = np.unique(day, return_inverse=True)            # 고유 day만
    labels = pd.to_datetime(uniq * 86400, unit="s").strftime("%Y-%m-%d").to_numpy()
    return pd.Series(labels[inv], index=ts.index)


# Result-level cache: 같은 (domain, start, end, content_types) query 가 다시 들어오면
# 모든 KPI 계산 skip 하고 응답 dict 그대로 반환.  도메인 토글 시 즉시 응답.
# REDIS_URL 환경변수 설정 시 Redis 백엔드 (multi-worker 공유), 미설정 시 in-process dict.
_RESULT_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_RESULT_CACHE_LOCK = threading.Lock()
_RESULT_CACHE_MAX = 80  # ~3 domains × 약간의 기간 조합

_REDIS_CLIENT = None
_REDIS_PREFIX = "mocha:kpi:"
_REDIS_TTL_S = 24 * 3600  # 24h — daily prewarm으로 갱신


def _redis_init() -> None:
    """Connect to Redis if REDIS_URL set. Lazily called on first cache access."""
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return
    import os
    url = os.environ.get("REDIS_URL")
    if not url:
        return
    try:
        import redis as _redis
        c = _redis.Redis.from_url(url, socket_timeout=2.0, socket_connect_timeout=2.0)
        c.ping()
        _REDIS_CLIENT = c
        logger.info("[kpi-cache] Redis backend: %s", url)
    except Exception:
        logger.exception("[kpi-cache] Redis init failed — falling back to in-process")


def _redis_key(key: tuple) -> str:
    # tuple key → stable string. repr() 은 tuple 구조 잘 보존.
    return _REDIS_PREFIX + repr(key)


def _cache_get(key: tuple) -> dict | None:
    _redis_init()
    if _REDIS_CLIENT is not None:
        try:
            import pickle
            raw = _REDIS_CLIENT.get(_redis_key(key))
            if raw is not None:
                return pickle.loads(raw)
        except Exception:
            logger.exception("[kpi-cache] redis get failed — falling back local")
    with _RESULT_CACHE_LOCK:
        v = _RESULT_CACHE.get(key)
        if v is not None:
            _RESULT_CACHE.move_to_end(key)
            # 참조 반환 시 호출부 mutation 이 캐시를 오염 → deepcopy 로 격리.
            # (Redis 백엔드는 pickle round-trip 으로 이미 격리됨 — 동작 일치)
            return copy.deepcopy(v)
        return None


def _cache_put(key: tuple, value: dict) -> None:
    _redis_init()
    if _REDIS_CLIENT is not None:
        try:
            import pickle
            _REDIS_CLIENT.setex(_redis_key(key), _REDIS_TTL_S, pickle.dumps(value))
            return
        except Exception:
            logger.exception("[kpi-cache] redis set failed — falling back local")
    with _RESULT_CACHE_LOCK:
        # 저장도 deepcopy — producer 가 put 이후 result 를 mutate/return 해도
        # 캐시본은 불변. (get 의 deepcopy 와 합쳐 양방향 격리 = Redis 와 동일)
        _RESULT_CACHE[key] = copy.deepcopy(value)
        _RESULT_CACHE.move_to_end(key)
        while len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)


def hydrate_cache(rows: list[tuple]) -> int:
    """DB 에서 가져온 (kind, domain, start, end, content_types, value_dict) 행들을
    in-memory result cache 로 채운다.  kind ∈ {'summary', 'series'}.

    NOTE: summary() 의 cache key 는 6-tuple (… cts_tuple, ats_tuple) 이라
    action_types 도 빈 tuple 로 명시해야 사용자 default query (no filter)
    에서 hit 한다.  이전 5-tuple 은 항상 miss → cold path 10s 가 매번 발생."""
    count = 0
    for kind, domain, start_iso, end_iso, cts_csv, val in rows:
        cts_tuple = tuple(c for c in (cts_csv or "").split(",") if c)
        key = (kind, domain, start_iso, end_iso, cts_tuple, ())
        _cache_put(key, val)
        count += 1
    return count


def _read_cached(path: str, domain: str) -> pd.DataFrame:
    key = (path, domain)
    mtime = os.path.getmtime(path)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] == mtime:
            _CACHE.move_to_end(key)
            return hit[1]
    raw = pd.read_feather(path)
    df = _preprocess(raw, domain)
    with _CACHE_LOCK:
        _CACHE[key] = (mtime, df)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return df


ARCHIVE = Path(os.environ.get("ARCHIVE_DIR", "/mnt/ml-archive"))

DOMAIN_LABEL = {
    "galaxy": "GALAXY · 왓챠피디아",
    "mars":   "MARS · 왓챠",
    "adult":  "ADULT · 성인+",
}

# Domain 목적별 보여줄 패널 명세.
# galaxy=평가 중심, mars=시청 중심, adult=구매 중심.
SUPPORTS = {
    "galaxy": {
        "rating_dist":  True,
        "revenue":      False,
        "ctype_donut":  True,
        "genre":        True,
        "meta_top":     True,   # graph_modeling/builtin 인기 감독/배우 (이름 포함)
        "hourly":       True,
        "pareto":       True,
        "meh_top":      True,   # MEH top contents (archive/mocha/mehs.ftr)
        "user_top":     True,   # 활동/소비 top user
    },
    "mars": {
        "rating_dist":  True,
        "revenue":      True,   # archive/mocha/mars_tvod_purchases.ftr (BQ hudson_us mirror)
        "ctype_donut":  True,
        "genre":        True,
        "meta_top":     True,
        "hourly":       True,
        "pareto":       True,
        "meh_top":      True,   # MEH top contents (archive/mocha/mehs.ftr)
        "user_top":     True,   # 활동/소비 top user
    },
    "adult": {
        "rating_dist":  False,
        "revenue":      True,   # 매출 패널 (메인)
        "ctype_donut":  False,  # 단일 type
        "genre":        False,
        "meta_top":     True,   # 인기 배우 / 감독
        "hourly":       True,
        "pareto":       True,
        "meh_top":      False,  # MEH 테이블에 AdultMovie/AdultWebtoon 실데이터 없음
        "user_top":     True,   # 결제(rental+possession) 기준 top user
    },
}

# 상단 KPI 카드 5개 (도메인별).  공통 3개(events·users·클릭율) + 특화 2개.
# Frontend 는 이 라벨 셋과 일치하는 KPI 를 hero 로 띄우고 나머지는 표.
# Hero / Table labels — abtest framework KPI 정의 (BaseKPIs + TvodKPIs) 기준만.
HERO_LABELS = {
    "galaxy": ["active_users", "1인당 RATE", "1인당 CLICK", "총 RATE", "UCPU"],
    "mars":   ["active_users", "1인당 PLAY", "1인당 CLICK", "총 PLAY", "UCPU"],
    "adult":  ["active_users", "1인당 CLICK", "1인당 구매(R+P)", "CVR", "PUR"],
}

TABLE_PRIORITY = {
    "galaxy": [
        "UCPU", "총 RATE", "총 WISH", "총 CLICK",
        "1인당 RATE", "1인당 WISH", "1인당 CLICK",
    ],
    "mars": [
        "UCPU", "총 PLAY", "총 WISH", "총 RATE", "총 CLICK",
        "1인당 PLAY", "1인당 WISH",
    ],
    "adult": [
        "UCPU", "총 CLICK", "총 RENTAL", "총 POSSESSION",
        "CVR", "CRPU", "PUR",
    ],
}

# GALAXY content_type 옵션
GALAXY_CONTENT_TYPES = [
    {"key": "movie",   "value": 1, "label": "Movie"},
    {"key": "tv",      "value": 2, "label": "TV"},
    {"key": "book",    "value": 4, "label": "Book"},
    {"key": "webtoon", "value": 8, "label": "Webtoon"},
]

# MARS content_type 옵션 (user_bert behavior_logs2 의 content prefix 기준)
MARS_CONTENT_TYPES = [
    {"key": "movie",         "value": 1,  "label": "Movie"},
    {"key": "tv",            "value": 2,  "label": "TV Season"},
    {"key": "webtoon",       "value": 8,  "label": "Webtoon"},
    {"key": "adult_movie",   "value": 10, "label": "Adult Movie"},
    {"key": "adult_webtoon", "value": 11, "label": "Adult Webtoon"},
]

# Action type 옵션 (도메인별, _preprocess 후 표준화된 라벨 기준)
ACTION_TYPES = {
    "galaxy": ["RATE", "WISH", "SEARCH", "CLICK"],
    "mars":   ["CLICK", "PLAY", "WISH", "SEARCH", "RATE"],
    "adult":  ["CLICK", "PREVIEW", "PLAY", "WISH", "RENTAL", "POSSESSION"],
}

# content_type code → 표시명 (모든 도메인 공통 도넛 라벨)
CONTENT_TYPE_LABEL = {
    1: "Movie", 2: "TV Season", 3: "TV Series", 4: "Book", 5: "TV Episode",
    6: "Album", 7: "Track", 8: "Webtoon", 9: "Webtoon Ep", 10: "Adult Movie",
    11: "Adult Webtoon", 12: "Adult Webtoon Ep",
}

# Domains that support genre breakdown (성인 제외, content type 별 meta 모두 cover)
GENRE_DOMAINS = {"galaxy", "mars"}


# ── content_id → title (Korean) — pulled from MySQL via remy-worker, pickled ──
_TITLE_LOCK = threading.Lock()
_TITLE_MAP: dict[str, str] | None = None
_TITLE_MAP_MTIME: float = 0.0
_TITLE_MAP_PATH = Path(__file__).parent / "_runtime" / "content_titles_ko.pkl"


def _load_title_map() -> dict[str, str]:
    """Lazy load with mtime-watch: pickle 갱신되면 다음 호출에서 자동 재로드.

    Source: books table + translations (Movie/TvSeason/...) via remy-worker.
    Path: _runtime/content_titles_ko.pkl. Returns {} if file missing.
    """
    global _TITLE_MAP, _TITLE_MAP_MTIME
    try:
        mtime = _TITLE_MAP_PATH.stat().st_mtime
    except FileNotFoundError:
        if _TITLE_MAP is None:
            _TITLE_MAP = {}
        return _TITLE_MAP
    if _TITLE_MAP is not None and mtime == _TITLE_MAP_MTIME:
        return _TITLE_MAP
    with _TITLE_LOCK:
        if _TITLE_MAP is not None and mtime == _TITLE_MAP_MTIME:
            return _TITLE_MAP
        import pickle
        with open(_TITLE_MAP_PATH, "rb") as f:
            _TITLE_MAP = pickle.load(f)
        _TITLE_MAP_MTIME = mtime
        return _TITLE_MAP


# ── genre metadata (lazy load from /archive/foundation_tmp) ──────
_GENRE_LOCK = threading.Lock()
_GENRE_MAP: dict[str, str] | None = None  # content_id ("1:1") -> main_genre_name


def _load_genre_map() -> dict[str, str]:
    """Lazy-load content_id → main_genre_name 매핑.

    foundation_tmp/items/{movie,tv_season,book,webtoon}/meta.parquet 다 읽어
    하나의 dict 로.  TvEpisode 는 main_genre 가 비어있어 skip.  ~1M 행 합쳐서
    ~50MB 메모리, 첫 호출 시 ~2-3 초.  이후 호출은 캐시 hit."""
    global _GENRE_MAP
    if _GENRE_MAP is not None:
        return _GENRE_MAP
    with _GENRE_LOCK:
        if _GENRE_MAP is not None:
            return _GENRE_MAP
        merged: dict[str, str] = {}
        for ct_dir in ("movie", "tv_season", "book", "webtoon"):
            p = ARCHIVE / "foundation_tmp" / "items" / ct_dir / "meta.parquet"
            if not p.exists():
                continue
            df = pd.read_parquet(p, columns=["content_id", "main_genre_name"])
            df = df[df["main_genre_name"].notna() & (df["main_genre_name"] != "")]
            for cid, g in zip(df["content_id"].astype(str), df["main_genre_name"], strict=False):
                merged[cid] = g
        _GENRE_MAP = merged
        return _GENRE_MAP


def _top_genres(df: pd.DataFrame, domain: str, n: int = 10) -> list[dict]:
    if domain not in GENRE_DOMAINS or df.empty or "content" not in df.columns:
        return []
    gm = _load_genre_map()
    # content→genre 를 raw 행에 직접 매핑한 뒤 genre 단위로 집계.
    # (이전엔 content별 nunique 를 genre로 sum → 한 유저가 같은 장르의 여러
    #  콘텐츠를 보면 중복 카운트됐음. genre 단위 nunique 로 정확히 계산)
    tmp = df[["user_id", "content"]].copy()
    tmp["genre"] = tmp["content"].astype(str).map(gm).fillna("미분류")
    g = tmp.groupby("genre", observed=True).agg(
        events=("user_id", "size"),
        users=("user_id", "nunique"),
    ).sort_values("events", ascending=False).head(n).reset_index()
    return [
        {"name": str(r["genre"]), "events": int(r["events"]), "users": int(r["users"])}
        for _, r in g.iterrows()
    ]


_RP_LOCK = threading.Lock()
_RP_DAILY: pd.DataFrame | None = None  # (date, content_type, value) → count 사전 집계


_RP_CACHE_PATH = Path(os.environ.get(
    "RP_CACHE_PATH",
    str(Path(__file__).resolve().parent / "_runtime" / "rp_daily.feather"),
))


def _load_rp_daily() -> pd.DataFrame:
    """rating_prediction 을 (KST date, content_type, value) 별 count 로 사전 집계.

    1회만 244M rows aggregate 후 디스크 feather 로 저장.  이후 시작 시 즉시 load.
    메모리 부담 줄이려고 chunk 처리."""
    global _RP_DAILY
    if _RP_DAILY is not None:
        return _RP_DAILY
    with _RP_LOCK:
        if _RP_DAILY is not None:
            return _RP_DAILY
        # 디스크 cache 우선
        if _RP_CACHE_PATH.exists():
            _RP_DAILY = pd.read_feather(_RP_CACHE_PATH)
            return _RP_DAILY
        # 첫 호출 — 직접 aggregate (메모리 절약 위해 chunk 처리)
        import pyarrow.feather as paf
        table = paf.read_table(
            str(ARCHIVE / "rating_prediction" / "default" / "ratings.ftr"),
            columns=["content", "value", "updated_at"],
        )
        df = table.to_pandas()
        del table
        # 유효 평점만 (1-10) + 작은 dtype
        df = df[(df["value"] >= 1) & (df["value"] <= 10)]
        df = df.assign(
            value=df["value"].astype("int8"),
            content_type=df["content"].astype(str).str.split(":").str[0].astype("int16"),
            date=df["updated_at"].dt.tz_convert("Asia/Seoul").dt.date,
        )[["date", "content_type", "value"]]
        agg = (
            df.groupby(["date", "content_type", "value"], observed=True)
              .size()
              .reset_index(name="count")
        )
        del df
        agg["count"] = agg["count"].astype("int64")
        _RP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        agg.to_feather(_RP_CACHE_PATH)
        _RP_DAILY = agg
        return _RP_DAILY


# content_type key → enum value mapping (galaxy/mars 공통)
_RP_CT_KEY_TO_VAL = {
    "movie": 1, "tv": 2, "book": 4, "webtoon": 8,
    "adult_movie": 10, "adult_webtoon": 11,
}


def _rating_distribution(
    df: pd.DataFrame,
    domain: str,
    start: date | None = None,
    end: date | None = None,
    content_types: list[str] | None = None,
) -> list[dict]:
    """평점 1-10 분포.  galaxy/mars 공유 (rating_prediction 의 같은 기간 데이터).

    필터 영향:
    - 기간 (start ~ end, KST)
    - content_types (콘텐츠 타입만 영향, 액션은 무관)"""
    if domain not in ("galaxy", "mars") or start is None or end is None:
        return []
    agg = _load_rp_daily()
    # 기간 필터
    sub = agg[(agg["date"] >= start) & (agg["date"] <= end)]
    # content_types 필터 (galaxy/mars 공통 — 각자 도메인의 valid types 만)
    if content_types:
        wanted = [_RP_CT_KEY_TO_VAL[c] for c in content_types if c in _RP_CT_KEY_TO_VAL]
        if wanted:
            sub = sub[sub["content_type"].isin(wanted)]
    if sub.empty:
        return []
    counts = sub.groupby("value")["count"].sum().sort_index()
    total = int(counts.sum())
    if total == 0:
        return []
    return [
        {"rating": int(v), "count": int(c), "share": float(c) / total}
        for v, c in counts.items()
    ]


# ── ADULT 가격 분포 ────────────────────────────────────────────
_PRICE_LOCK = threading.Lock()
_PRICE_MAP: dict | None = None  # {"rental": {cid:price}, "possession": {cid:price}}


def _load_adult_prices() -> dict:
    """/archive/rec_adult/builtin/CONTENT_TO_PRICE.pkl lazy-load."""
    global _PRICE_MAP
    if _PRICE_MAP is not None:
        return _PRICE_MAP
    with _PRICE_LOCK:
        if _PRICE_MAP is not None:
            return _PRICE_MAP
        import pickle
        with open(ARCHIVE / "rec_adult" / "builtin" / "CONTENT_TO_PRICE.pkl", "rb") as f:
            _PRICE_MAP = pickle.load(f)
        return _PRICE_MAP


# 가격 bin: 0-1000 / 1000-2000 / 2000-3000 / ... / 10000+
_PRICE_BINS = [0, 1000, 2000, 3000, 4000, 5000, 7000, 10000, 99999999]
_PRICE_LABELS = ["~1k", "1-2k", "2-3k", "3-4k", "4-5k", "5-7k", "7-10k", "10k+"]


def _adult_price_series(
    purch: pd.DataFrame, rental_map: dict, poss_map: dict
) -> pd.Series:
    """행별 매출을 벡터화 계산: RENTAL→rental_map, POSSESSION→poss_map, else 0.

    content 의 ':' 뒤 토큰을 cid 로 보고 int-key 우선 → str-key fallback (map 은
    int/float 키를 hash 동일 취급). 이전 per-row apply(_row_price) 의 대체.
    """
    act = purch["action_type"].astype(str)
    cid = purch["content"].astype(str).str.split(":").str[-1]
    cid_num = pd.to_numeric(cid, errors="coerce")  # 숫자 cid 면 값, 아니면 NaN

    def _lookup(pmap: dict) -> pd.Series:
        return cid_num.map(pmap).fillna(cid.map(pmap))

    price = pd.Series(0.0, index=purch.index)
    price = price.mask(act == "RENTAL", _lookup(rental_map))
    price = price.mask(act == "POSSESSION", _lookup(poss_map))
    return price.fillna(0).astype("int64")


def _adult_top_revenue_contents(df: pd.DataFrame, domain: str, n: int = 10) -> list[dict]:
    """ADULT — TOP N 매출 아이템.  rental + possession 매출 합 기준."""
    if domain != "adult" or df.empty:
        return []
    prices = _load_adult_prices()
    rental_map = prices.get("rental", {})
    poss_map = prices.get("possession", {})
    purch = df[df["action_type"].astype(str).isin(["RENTAL", "POSSESSION"])].copy()
    if purch.empty:
        return []
    purch["price"] = _adult_price_series(purch, rental_map, poss_map)
    g = purch.groupby("content", observed=True).agg(
        revenue=("price", "sum"),
        purchases=("price", "size"),
        users=("user_id", "nunique"),
    ).sort_values("revenue", ascending=False).head(n).reset_index()
    tm = _load_title_map()
    return [
        {"content": str(r["content"]), "title": tm.get(str(r["content"]), ""),
         "revenue": int(r["revenue"]),
         "purchases": int(r["purchases"]), "users": int(r["users"])}
        for _, r in g.iterrows()
    ]


def _adult_revenue(df: pd.DataFrame, domain: str) -> dict:
    """ADULT — 기간 총매출 + 1인당 매출(구매자 기준) + 일자별 매출."""
    if domain != "adult" or df.empty:
        return {"available": False}
    prices = _load_adult_prices()
    rental_map = prices.get("rental", {})
    poss_map = prices.get("possession", {})

    purch = df[df["action_type"].astype(str).isin(["RENTAL", "POSSESSION"])].copy()
    if purch.empty:
        return {"available": True, "total_revenue": 0, "paying_users": 0,
                "revenue_per_paying_user": 0, "daily_revenue": []}
    purch["price"] = _adult_price_series(purch, rental_map, poss_map)
    total_rev = int(purch["price"].sum())
    paying_users = int(purch["user_id"].nunique())
    arppu = float(total_rev) / paying_users if paying_users else 0.0
    daily = purch.groupby("date", observed=True).agg(
        revenue=("price", "sum"),
        purchases=("price", "size"),
        users=("user_id", "nunique"),
    ).sort_index().reset_index()
    top_payers = purch.groupby("user_id", observed=True).agg(
        revenue=("price", "sum"),
        purchases=("price", "size"),
    ).sort_values("revenue", ascending=False).head(10).reset_index()
    return {
        "available": True,
        "total_revenue": total_rev,
        "paying_users": paying_users,
        "revenue_per_paying_user": arppu,
        "daily_revenue": [
            {"date": r["date"], "revenue": int(r["revenue"]),
             "purchases": int(r["purchases"]), "users": int(r["users"])}
            for _, r in daily.iterrows()
        ],
        "top_payers": [
            {"user_id": int(r["user_id"]), "revenue": int(r["revenue"]),
             "purchases": int(r["purchases"])}
            for _, r in top_payers.iterrows()
        ],
    }


# ── ADULT 인기 메타 (배우/감독) ────────────────────────────────
_META_LOCK = threading.Lock()
_META_MAPS: dict[str, object] | None = None


def _load_adult_metas() -> dict:
    """CID_TO_ACTORID / CID_TO_DIRECTORID 등 sparse matrix 로드.

    Adult content_id (10:XXXX 의 XXXX) → metadata id list."""
    global _META_MAPS
    if _META_MAPS is not None:
        return _META_MAPS
    with _META_LOCK:
        if _META_MAPS is not None:
            return _META_MAPS
        import pickle
        out = {}
        for kind, fname in [("actor", "CID_TO_ACTORID.pkl"),
                            ("director", "CID_TO_DIRECTORID.pkl")]:
            p = ARCHIVE / "rec_adult" / "builtin" / fname
            try:
                with open(p, "rb") as f:
                    m = pickle.load(f).tocsr()
                out[kind] = m
            except Exception:
                pass
        _META_MAPS = out
        return out


_GRAPH_META_LOCK = threading.Lock()
_GRAPH_META: dict | None = None


def _load_graph_meta() -> dict:
    """graph_modeling/builtin 메타 lazy-load.

    Returns dict: contents_list, cid_to_idx, credit_edges (np array),
    person_id_to_name (dict)."""
    global _GRAPH_META
    if _GRAPH_META is not None:
        return _GRAPH_META
    with _GRAPH_META_LOCK:
        if _GRAPH_META is not None:
            return _GRAPH_META
        import pickle

        base = ARCHIVE / "graph_modeling" / "builtin"
        with open(f"{base}/contents.pkl", "rb") as f: contents = pickle.load(f)
        with open(f"{base}/content_credit_edges.pkl", "rb") as f: cc = pickle.load(f)
        with open(f"{base}/person_id_to_name.pkl", "rb") as f: pn = pickle.load(f)
        cid_to_idx = {c: i for i, c in enumerate(contents)}
        _GRAPH_META = {
            "contents": contents,
            "cid_to_idx": cid_to_idx,
            "credit_edges": cc,
            "person_id_to_name": pn,
        }
        return _GRAPH_META


def _galaxy_mars_meta_top(df: pd.DataFrame, kind: str, n: int = 10) -> list[dict]:
    """GALAXY/MARS — events 가중 인기 감독/배우 TOP N (이름 포함)."""
    if df.empty or "content" not in df.columns:
        return []
    import numpy as np
    meta = _load_graph_meta()
    contents = meta["contents"]
    cid_to_idx = meta["cid_to_idx"]
    cc = meta["credit_edges"]
    pn = meta["person_id_to_name"]
    # df content → idx → events count
    idx_series = df["content"].astype(str).map(cid_to_idx).dropna().astype(int)
    if idx_series.empty:
        return []
    cnt = idx_series.value_counts()
    cnt_arr = np.zeros(len(contents), dtype=np.float64)
    cnt_arr[cnt.index.values] = cnt.values
    # filter credit edges by type. 0=director, 1/2=actor
    if kind == "director":
        type_mask = cc[:, 2] == 0
    elif kind == "actor":
        type_mask = (cc[:, 2] == 1) | (cc[:, 2] == 2)
    else:
        return []
    cc_t = cc[type_mask]
    # Some credit-edge content_idx values can exceed len(contents) — bound them.
    cc_t = cc_t[cc_t[:, 0] < len(contents)]
    if len(cc_t) == 0:
        return []
    content_idxs = cc_t[:, 0].astype(int)
    person_ids = cc_t[:, 1].astype(int)
    weights = cnt_arr[content_idxs] * cc_t[:, 3]    # weight col[3]
    if weights.sum() == 0:
        return []
    agg = pd.Series(weights).groupby(person_ids).sum().sort_values(ascending=False).head(n)
    out = []
    for pid, w in agg.items():
        name = str(pn.get(int(pid), f"#{pid}"))
        # strip prefix "감독: " or "주연: "
        if ": " in name:
            name = name.split(": ", 1)[1]
        out.append({"meta_id": int(pid), "label": name, "count": int(round(w))})
    return out


def _adult_meta_top(df: pd.DataFrame, domain: str, kind: str, n: int = 10) -> list[dict]:
    """ADULT 도메인 — 인기 actor/director TOP N (purchase events 가중치)."""
    if domain != "adult" or df.empty:
        return []
    metas = _load_adult_metas()
    m = metas.get(kind)
    if m is None:
        return []
    # purchase events 만 가중치 — 구매 인기 측정 의도
    sub = df[df["action_type"].astype(str).isin(["RENTAL", "POSSESSION"])]
    if sub.empty:
        sub = df[df["action_type"].astype(str) == "CLICK"]  # fallback to clicks
    if sub.empty:
        return []
    # content_id 추출 (10:XXX → XXX int)
    cids = sub["content"].astype(str).str.split(":").str[-1]
    cid_ints = []
    for c in cids:
        try: cid_ints.append(int(c))
        except ValueError: pass
    if not cid_ints:
        return []
    # CID_TO_ACTORID/DIRECTORID 는 설계상 row index == content_id (loader docstring
    # "Adult content_id → metadata id list" 참조). graph_modeling 메타와 달리
    # 별도 cid_to_idx 매핑이 필요 없음. 범위 밖 cid 는 drop.
    import numpy as np
    rows = np.array(cid_ints)
    rows = rows[rows < m.shape[0]]
    if len(rows) == 0:
        return []
    # 각 row 의 column 1 위치를 가중치 1로 누적
    counts = np.array(m[rows].sum(axis=0)).ravel()
    top = counts.argsort()[::-1][:n]
    return [
        {"meta_id": int(i), "count": int(counts[i])}
        for i in top if counts[i] > 0
    ]


def _adult_price_distribution(df: pd.DataFrame, domain: str) -> dict:
    """ADULT 도메인 — rental / possession 행동의 가격 분포.

    behavior_logs 의 content_id 를 CONTENT_TO_PRICE 에 join 해서 가격을 얻고
    구간별 events 수 + 총 매출(원) 계산."""
    if domain != "adult" or df.empty or "action_type" not in df.columns:
        return {"rental": [], "possession": [], "total_revenue": 0, "available": False}
    prices = _load_adult_prices()
    rental_map = prices.get("rental", {})
    poss_map = prices.get("possession", {})

    def _bin_dist(action: str, pmap: dict) -> tuple[list[dict], int]:
        sub = df[df["action_type"].astype(str) == action]
        if sub.empty:
            return [], 0
        # content_id 추출 (10:xxxx 형식) — pmap은 그냥 integer key 인 듯, 둘 다 시도
        cids = sub["content"].astype(str).str.split(":").str[-1]
        # Try int key first
        prices_list = []
        for c in cids:
            try:
                p = pmap.get(int(c))
            except ValueError:
                p = None
            if p is None:
                p = pmap.get(c)
            if p is not None:
                prices_list.append(p)
        if not prices_list:
            return [], 0
        s = pd.Series(prices_list)
        binned = pd.cut(s, bins=_PRICE_BINS, labels=_PRICE_LABELS, right=False)
        counts = binned.value_counts().sort_index()
        total = int(counts.sum())
        revenue = int(s.sum())
        return [
            {"bin": str(b), "count": int(c), "share": float(c) / total}
            for b, c in counts.items() if c > 0
        ], revenue

    rental_dist, rental_rev = _bin_dist("RENTAL", rental_map)
    poss_dist, poss_rev = _bin_dist("POSSESSION", poss_map)
    return {
        "available": True,
        "rental": rental_dist,
        "possession": poss_dist,
        "rental_revenue": rental_rev,
        "possession_revenue": poss_rev,
        "total_revenue": rental_rev + poss_rev,
    }


def _hourly_activity(df: pd.DataFrame) -> list[dict]:
    """KST 시간(0-23)별 events. peak hour 모니터링용."""
    if df.empty or "timestamp" not in df.columns:
        return []
    ts = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert("Asia/Seoul")
    hours = ts.dt.hour.value_counts().sort_index()
    return [{"hour": int(h), "count": int(c)} for h, c in hours.items()]


_PARETO_PCT = [0.01, 0.05, 0.1, 0.2, 0.5, 1.0]


def _pareto_curve(df: pd.DataFrame) -> list[dict]:
    """콘텐츠 Top X% 가 events 의 몇 % 점유 — Long-tail 시각화."""
    if df.empty or "content" not in df.columns:
        return []
    counts = df["content"].value_counts().sort_values(ascending=False)
    total = float(counts.sum())
    if total <= 0 or len(counts) == 0:
        return []
    cum = counts.cumsum() / total
    out = []
    for p in _PARETO_PCT:
        n = max(1, int(len(counts) * p))
        share = float(cum.iloc[n - 1])
        out.append({"top_pct": p, "share": share})
    return out


def _content_type_breakdown(df: pd.DataFrame) -> list[dict]:
    """content_type 코드별 events 합 — 도넛 차트용."""
    if df.empty or "content" not in df.columns:
        return []
    prefix = df["content"].astype(str).str.split(":").str[0]
    counts = prefix.value_counts()
    out = []
    for code, cnt in counts.items():
        try:
            label = CONTENT_TYPE_LABEL.get(int(code), code)
        except ValueError:
            label = code
        out.append({"code": str(code), "label": str(label), "count": int(cnt)})
    return out


@dataclass
class FileSpec:
    path: str
    start: date
    end: date


_NAME_RE = re.compile(r"(\d{8})_(\d{8})\.ftr$")


def _parse_name(p: str) -> tuple[date, date] | None:
    m = _NAME_RE.search(p)
    if not m:
        return None
    try:
        return (
            datetime.strptime(m.group(1), "%Y%m%d").date(),
            datetime.strptime(m.group(2), "%Y%m%d").date(),
        )
    except ValueError:
        return None


def _domain_files(domain: str) -> list[FileSpec]:
    """Enumerate all candidate ftr files for the domain."""
    if domain == "galaxy":
        roots = [ARCHIVE / "rec_galaxy" / "behavior_logs"]
    elif domain == "mars":
        roots = [ARCHIVE / "user_bert" / "behavior_logs2" / "train"]
    elif domain == "adult":
        roots = [ARCHIVE / "rec_adult" / "behavior_logs"]
    else:
        return []
    specs = []
    for root in roots:
        for p in glob.glob(str(root / "*.ftr")):
            r = _parse_name(p)
            if r:
                specs.append(FileSpec(p, r[0], r[1]))
    return specs


def _pick_files(specs: list[FileSpec], start: date, end: date) -> list[FileSpec]:
    """Pick the *longest-cover* file for each day in [start, end].

    Files share the pattern start_end.ftr — multiple files may share the
    same end with different starts.  The widest cover (smallest start) is
    the most complete snapshot, so we prefer it.  De-duplicated by path.
    """
    overlap = [s for s in specs if not (s.end < start or s.start > end)]
    by_day: dict[date, FileSpec] = {}
    for s in overlap:
        first = max(s.start, start)
        last = min(s.end, end)
        for off in range((last - first).days + 1):
            d = first + timedelta(days=off)
            cur = by_day.get(d)
            cur_span = (cur.end - cur.start).days if cur else -1
            new_span = (s.end - s.start).days
            # prefer the longer cover; break ties by older start
            if new_span > cur_span or (new_span == cur_span and (not cur or s.start < cur.start)):
                by_day[d] = s
    unique: dict[str, FileSpec] = {}
    for s in by_day.values():
        unique[s.path] = s
    return list(unique.values())


def _load(specs: list[FileSpec], start: date, end: date, domain: str) -> pd.DataFrame:
    """Read + filter behavior_logs for the query range.

    Each file is preprocessed once (normalized action_type, KST date)
    inside the cache, so the only per-query work here is timestamp
    boolean-indexing on the cached frame and concat."""
    if not specs:
        return pd.DataFrame()
    # KST 자정 기준 timestamp window. behavior 로그 timestamp 는 unix UTC sec
    # 인데 'date' 컬럼은 KST 자정 기준 grouping 이라 boundary 를 맞춰야 한다.
    start_ts = int(datetime.combine(start, datetime.min.time(), tzinfo=KST).timestamp())
    end_ts = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=KST).timestamp())
    parts = []
    for s in specs:
        df = _read_cached(s.path, domain)
        if "timestamp" in df.columns:
            # boolean-mask 인덱싱은 pandas 가 copy 를 반환 → 캐시 프레임과 분리됨.
            df = df[(df["timestamp"] >= start_ts) & (df["timestamp"] < end_ts)]
        else:
            # 필터 없으면 _read_cached 의 캐시 참조가 그대로 새어나감 → 방어 copy.
            df = df.copy()
        parts.append(df)
    if len(parts) == 1:
        return parts[0]
    return pd.concat(parts, ignore_index=True)


# ── Fast top-N path (DuckDB over columnar feather) ──────────────
# 큰 윈도우(예: 1년)에서 full summary 는 12개 월별 파일(4GB)을 전부 preprocess +
# 모든 panel 계산 → 13분. top-N 질문은 content/action_type/timestamp 3컬럼만
# columnar 로 스캔 + DuckDB 집계 → 5~6초 (exact). 캐시/사전집계 불필요.

def _raw_action_filter(domain: str, action: str) -> str:
    """정규화된 action 라벨("PLAY"/"RATE"/...) → 해당 도메인 raw feather 의
    action_type 값에 맞는 DuckDB WHERE 절 (raw 표현이 도메인마다 다름).

      - mars  : "PLAY:MARS" 등 "{ACTION}:MARS" (galaxy 이벤트 섞여있어 :MARS 필수)
      - adult : 소문자 "play"
      - galaxy: int 코드 (RATE=1 WISH=2 SEARCH=6 CLICK=7)
    """
    a = action.upper()
    if domain == "mars":
        return f"action_type = '{a}:MARS'"
    if domain == "adult":
        return f"action_type = '{a.lower()}'"
    if domain == "galaxy":
        code = {"RATE": 1, "WISH": 2, "SEARCH": 6, "CLICK": 7}.get(a)
        if code is None:
            raise ValueError(f"galaxy action 미지원: {action}")
        return f"action_type = {code}"
    raise ValueError(f"domain 미지원: {domain}")


def top_items(domain: str, action: str, start: date, end: date,
              n: int = 10, content_types: list[int] | None = None) -> list[dict]:
    """기간 내 `action` 가장 많이 발생한 콘텐츠 TOP N (exact, fast).

    full summary 를 우회하고 content/action_type/timestamp 3컬럼만 columnar 로
    읽어 DuckDB 로 집계. KST 자정 경계로 timestamp 필터(정확). content_types 지정
    시 해당 content_type prefix 만 (1=Movie 2=TvSeason ...).

    Returns: list of {content, title, count} — count desc.
    """
    import duckdb
    import pyarrow as pa
    import pyarrow.feather as feather

    specs = _pick_files(_domain_files(domain), start, end)
    if not specs:
        return []
    start_ts = int(datetime.combine(start, datetime.min.time(), tzinfo=KST).timestamp())
    end_ts = int(datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=KST).timestamp())

    tables = []
    for s in specs:
        try:
            tables.append(feather.read_table(s.path, columns=["content", "action_type", "timestamp"]))
        except Exception:
            logger.exception("[top_items] read failed: %s", s.path)
    if not tables:
        return []
    tbl = pa.concat_tables(tables)  # noqa: F841 — DuckDB 가 이름으로 참조

    where = [_raw_action_filter(domain, action),
             f"timestamp >= {start_ts}", f"timestamp < {end_ts}"]
    if content_types:
        likes = " OR ".join(f"content LIKE '{int(ct)}:%'" for ct in content_types)
        where.append(f"({likes})")
    sql = (
        "SELECT content, count(*) AS cnt FROM tbl WHERE "
        + " AND ".join(where)
        + f" GROUP BY content ORDER BY cnt DESC LIMIT {int(n)}"
    )
    rows = duckdb.sql(sql).fetchall()
    tm = _load_title_map()
    return [{"content": str(c), "title": tm.get(str(c), ""), "count": int(cnt)}
            for c, cnt in rows]


# ── KPI calculators ─────────────────────────────────────────────

def _safe_div(a: float, b: float) -> float:
    return float(a) / float(b) if b else 0.0


def _user_action_pivot(df: pd.DataFrame) -> pd.DataFrame:
    """user_id × action_type count pivot — KPI 계산을 한 번에 처리하기 위한
    사전 집계.  큰 df 에서 여러 번 groupby 하는 비용을 한 번으로 압축."""
    return (
        df.groupby(["user_id", "action_type"], observed=True)
        .size()
        .unstack(fill_value=0)
    )


def _per_user(ua: pd.DataFrame, action: str) -> float:
    """평균 action 횟수 = (action 합) / (총 user 수)."""
    if action not in ua.columns or len(ua) == 0:
        return 0.0
    return float(ua[action].sum()) / len(ua)


def _binary_rate(ua: pd.DataFrame, action: str) -> float:
    """action 한번이라도 한 user 비율."""
    if action not in ua.columns or len(ua) == 0:
        return 0.0
    return float((ua[action] > 0).sum()) / len(ua)


def _ratio_total(ua: pd.DataFrame, num: str, den: str) -> float:
    a = float(ua[num].sum()) if num in ua.columns else 0.0
    b = float(ua[den].sum()) if den in ua.columns else 0.0
    return _safe_div(a, b)


def _replay_rate(ua: pd.DataFrame, action: str) -> float:
    """한번이라도 action 한 user 중 2회 이상 한 user 비율."""
    if action not in ua.columns:
        return 0.0
    col = ua[action]
    base = int((col >= 1).sum())
    return _safe_div(int((col >= 2).sum()), base)


def _per_user_ratio_mean(ua: pd.DataFrame, num: str, den: str) -> float:
    """abtest CRPU/CTRPU 공식: 유저별로 (num/den) 비율 계산 → 평균.

    den=0 유저는 0으로 처리 (abtest framework 의 fillna(0) 와 동일)."""
    if num not in ua.columns or den not in ua.columns or len(ua) == 0:
        return 0.0
    num_col = ua[num].astype(float)
    den_col = ua[den].astype(float)
    ratio = (num_col / den_col).replace([float("inf"), -float("inf")], 0).fillna(0)
    return float(ratio.mean())


def _ucpu(df: pd.DataFrame, ua: pd.DataFrame) -> float:
    """abtest UCPU: 유저별 unique content 수 → 평균."""
    if df.empty or "content" not in df.columns:
        return 0.0
    per_user = df.groupby("user_id", observed=True)["content"].nunique()
    return float(per_user.mean()) if len(per_user) else 0.0


# ── EDA 기반 모니터링 KPI (노션 EDA 보고서 인사이트) ─────────────────

def _cold_start_rate(ua: pd.DataFrame, threshold: int = 10) -> float:
    """Cold Start = N회 이하 활동 user 비율 (노션 EDA 기준 10회)."""
    if len(ua) == 0: return 0.0
    return float((ua.sum(axis=1) <= threshold).sum()) / len(ua)


def _heavy_user_rate(ua: pd.DataFrame, threshold: int = 50) -> float:
    """Heavy User = 일정 이상 활동 user 비율."""
    if len(ua) == 0: return 0.0
    return float((ua.sum(axis=1) >= threshold).sum()) / len(ua)


def _long_tail_share(df: pd.DataFrame, top_pct: float = 0.05) -> float:
    """상위 X% 콘텐츠가 차지하는 events 점유율 (Pareto)."""
    if df.empty or "content" not in df.columns: return 0.0
    c = df["content"].value_counts()
    if len(c) == 0: return 0.0
    n_top = max(1, int(len(c) * top_pct))
    return float(c.iloc[:n_top].sum()) / float(c.sum())


_STRONG_ACTIONS = {
    "galaxy": {"RATE", "WISH"},
    "mars":   {"RATE", "WISH", "PLAY"},
    "adult":  {"RENTAL", "POSSESSION", "WISH"},
}


def _strong_signal_rate(df: pd.DataFrame, domain: str) -> float:
    """Strong action 비율 — 추천 시스템에서 모델 학습 신호로 쓰는 action / 전체."""
    if df.empty or "action_type" not in df.columns: return 0.0
    strong = _STRONG_ACTIONS.get(domain, set())
    return float(df["action_type"].astype(str).isin(strong).sum()) / len(df)


def _sparsity(n_events: int, n_users: int, n_contents: int) -> float:
    """1 - events / (users × contents)  — 매트릭스 희소성."""
    denom = float(n_users) * float(n_contents)
    if denom <= 0: return 0.0
    return max(0.0, 1.0 - float(n_events) / denom)


def _revisit_rate(df: pd.DataFrame, ua: pd.DataFrame) -> float:
    """동일 (user, content) 재방문 비율 — 1보다 큰 (user, content) pair / 전체 pairs."""
    if df.empty or "content" not in df.columns: return 0.0
    pairs = df.groupby(["user_id", "content"], observed=True).size()
    if len(pairs) == 0: return 0.0
    return float((pairs >= 2).sum()) / float(len(pairs))


def _avg_rating(df: pd.DataFrame, domain: str) -> float:
    """평점 평균 — RATE action 만, 1-10 점만 (missing/-1 제외)."""
    if df.empty: return 0.0
    rate_mask = df["action_type"].astype(str) == "RATE"
    if domain == "galaxy" and "value" in df.columns:
        vals = df.loc[rate_mask, "value"]
        valid = vals[(vals >= 1) & (vals <= 10)]
        return float(valid.mean()) if len(valid) else 0.0
    if domain == "mars" and "rating" in df.columns:
        vals = df.loc[rate_mask, "rating"]
        valid = vals[(vals >= 1) & (vals <= 10)]
        return float(valid.mean()) if len(valid) else 0.0
    return 0.0


def _top_rated_contents(df: pd.DataFrame, domain: str, n: int = 10, min_count: int = 10) -> list[dict]:
    """평점 높은 콘텐츠 TOP N — RATE action 기준 평균 평점.

    min_count: 신뢰 가능한 평균을 위해 최소 평가 수 (1번만 평가받은 콘텐츠 제외).
    """
    if domain not in ("galaxy", "mars") or df.empty:
        return []
    rate_mask = df["action_type"].astype(str) == "RATE"
    rate_col = "value" if domain == "galaxy" else "rating"
    if rate_col not in df.columns:
        return []
    rated = df.loc[rate_mask, ["content", rate_col]].rename(columns={rate_col: "rating"})
    rated = rated[(rated["rating"] >= 1) & (rated["rating"] <= 10)]
    if rated.empty:
        return []
    g = rated.groupby("content", observed=True)["rating"].agg(["mean", "count"]).reset_index()
    g = g[g["count"] >= min_count]
    if g.empty:
        # min_count 충족 콘텐츠 없으면 threshold 완화
        g = rated.groupby("content", observed=True)["rating"].agg(["mean", "count"]).reset_index()
        g = g[g["count"] >= max(2, min_count // 5)]
    g = g.sort_values(["mean", "count"], ascending=[False, False]).head(n)
    tm = _load_title_map()
    return [
        {"content": str(r["content"]), "title": tm.get(str(r["content"]), ""),
         "avg_rating": round(float(r["mean"]), 2),
         "rate_count": int(r["count"])}
        for _, r in g.iterrows()
    ]


def _top_users(df: pd.DataFrame, domain: str, n: int = 10) -> list[dict]:
    """도메인별 활동/소비 TOP N 유저.

    기준 (도메인별 가용 metric):
      - galaxy : 총 액션 수 (RATE + WISH + SEARCH + CLICK) — '활동량'
      - mars   : 총 PLAY 수 — '시청 활동량' (PLAY 가 없으면 총 액션)
      - adult  : 결제 수 (RENTAL + POSSESSION) — '소비'

    archive feather 내 user_id 기준 단순 집계. 도메인 합산은 다루지 않음 — user_id
    공간은 공유되나 metric 단위가 도메인별로 다르므로 도메인-내 ranking 만 의미가
    있음. cross-domain 분석은 별도 작업.

    Returns: list of {user_id, events, contents, metric}
      - events  : 해당 metric 의 행위 수 (정렬 기준)
      - contents: 해당 user 가 손댄 unique content 수 (diversity 보조 지표)
      - metric  : "활동" | "PLAY" | "결제" (UI 라벨)
    """
    if df.empty or "user_id" not in df.columns:
        return []
    if domain == "adult":
        purch = df[df["action_type"].astype(str).isin(["RENTAL", "POSSESSION"])]
        if purch.empty:
            return []
        g = purch.groupby("user_id", observed=True).agg(
            events=("user_id", "size"),
            contents=("content", "nunique"),
        ).sort_values("events", ascending=False).head(n).reset_index()
        metric_label = "결제"
    elif domain == "mars":
        plays = df[df["action_type"].astype(str) == "PLAY"]
        target = plays if not plays.empty else df
        g = target.groupby("user_id", observed=True).agg(
            events=("user_id", "size"),
            contents=("content", "nunique"),
        ).sort_values("events", ascending=False).head(n).reset_index()
        metric_label = "PLAY" if not plays.empty else "활동"
    elif domain == "galaxy":
        g = df.groupby("user_id", observed=True).agg(
            events=("user_id", "size"),
            contents=("content", "nunique"),
        ).sort_values("events", ascending=False).head(n).reset_index()
        metric_label = "활동"
    else:
        return []
    return [
        {"user_id": int(r["user_id"]),
         "events": int(r["events"]),
         "contents": int(r["contents"]),
         "metric": metric_label}
        for _, r in g.iterrows()
    ]


def _mars_revenue(start: date, end: date) -> dict:
    """MARS TVOD — 기간 총매출 + 1인당 매출 + 일자별 매출.

    Source: `/archive/mocha/mars_tvod_purchases.ftr` (BQ hudson_us.rentals +
    possessions + payments JOIN 결과). adult content (16/32) 는 제외 — adult
    도메인이 별도 panel.
    """
    from data_sources.archive import read_mars_tvod_purchases  # lazy
    try:
        df = read_mars_tvod_purchases(start, end)
    except FileNotFoundError:
        return {"available": False}
    if df.empty:
        return {"available": True, "total_revenue": 0, "paying_users": 0,
                "revenue_per_paying_user": 0, "daily_revenue": [], "top_payers": []}
    # mars 도메인 content_type만 (Adult 제외 — rec_adult 패널이 별도)
    df = df[df["content_type"].isin([1, 2, 128, 8])].copy()
    if df.empty:
        return {"available": True, "total_revenue": 0, "paying_users": 0,
                "revenue_per_paying_user": 0, "daily_revenue": [], "top_payers": []}
    df["amount_cents"] = df["amount_cents"].fillna(0).astype(int)
    df["date"] = pd.to_datetime(df["created_at"], unit="s", utc=True) \
                   .dt.tz_convert("Asia/Seoul").dt.date.astype(str)
    total_rev = int(df["amount_cents"].sum())
    paying_users = int(df["user_id"].nunique())
    arppu = float(total_rev) / paying_users if paying_users else 0.0
    daily = df.groupby("date", observed=True).agg(
        revenue=("amount_cents", "sum"),
        purchases=("amount_cents", "size"),
        users=("user_id", "nunique"),
    ).sort_index().reset_index()
    top_payers = df.groupby("user_id", observed=True).agg(
        revenue=("amount_cents", "sum"),
        purchases=("amount_cents", "size"),
    ).sort_values("revenue", ascending=False).head(10).reset_index()
    return {
        "available": True,
        "total_revenue": total_rev,
        "paying_users": paying_users,
        "revenue_per_paying_user": arppu,
        "daily_revenue": [
            {"date": r["date"], "revenue": int(r["revenue"]),
             "purchases": int(r["purchases"]), "users": int(r["users"])}
            for _, r in daily.iterrows()
        ],
        "top_payers": [
            {"user_id": int(r["user_id"]), "revenue": int(r["revenue"]),
             "purchases": int(r["purchases"])}
            for _, r in top_payers.iterrows()
        ],
    }


def _mars_top_revenue_contents(start: date, end: date, n: int = 10) -> list[dict]:
    """MARS TVOD — TOP N 매출 콘텐츠 (Movie / TvSeason / TvEpisode / Webtoon).

    Returns: list of {content, title, revenue, purchases, users}
      - content : "{content_type_int}:{item_id}" (e.g. "1:1584718")
      - title   : `_load_title_map()` lookup. 없으면 빈 string.
      - revenue : KRW 합산 (payments.amount_cents). 같은 invoice 가 여러 item
                  묶은 경우 약간 over-count 가능
      - purchases : 해당 콘텐츠 결제 row 수
      - users     : 결제한 unique user 수
    """
    from data_sources.archive import read_mars_tvod_purchases  # lazy
    try:
        df = read_mars_tvod_purchases(start, end)
    except FileNotFoundError:
        return []
    if df.empty:
        return []
    df = df[df["content_type"].isin([1, 2, 128, 8])].copy()
    if df.empty:
        return []
    df["amount_cents"] = df["amount_cents"].fillna(0).astype(int)
    g = df.groupby("content", observed=True).agg(
        revenue=("amount_cents", "sum"),
        purchases=("amount_cents", "size"),
        users=("user_id", "nunique"),
    ).sort_values("revenue", ascending=False).head(n).reset_index()
    tm = _load_title_map()
    return [
        {"content": str(r["content"]), "title": tm.get(str(r["content"]), ""),
         "revenue": int(r["revenue"]),
         "purchases": int(r["purchases"]), "users": int(r["users"])}
        for _, r in g.iterrows()
    ]


def _top_meh_contents(domain: str, start: date, end: date, n: int = 10) -> list[dict]:
    """부정 피드백 TOP N 콘텐츠 — 같은 콘텐츠가 가장 많이 'meh'(별로에요) 받은 순.

    Source: `/archive/mocha/mehs.ftr` (BQ `gretel.frograms_us.mehs` 풀 dump).
    Cross-platform single file — domain은 content_type 으로만 분기.
      - galaxy : content_type ∈ {1, 2, 4, 8} (Movie/TvSeason/Book/Webtoon)
      - mars   : content_type ∈ {1, 2}      (Movie/TvSeason)
      - adult  : MEH 테이블에 실데이터 없음 → 빈 list
    """
    if domain not in ("galaxy", "mars"):
        return []
    from data_sources.archive import read_mehs  # lazy — keep main.py import-safe when /archive unmounted
    try:
        mdf = read_mehs(start, end)
    except FileNotFoundError:
        return []
    if mdf.empty:
        return []
    ct_filter = [1, 2, 4, 8] if domain == "galaxy" else [1, 2]
    mdf = mdf[mdf["content_type"].isin(ct_filter)]
    if mdf.empty:
        return []
    g = mdf.groupby("content", observed=True).agg(
        meh_count=("user_id", "size"),
        users=("user_id", "nunique"),
    ).sort_values(["meh_count", "users"], ascending=[False, False]).head(n).reset_index()
    tm = _load_title_map()
    return [
        {"content": str(r["content"]), "title": tm.get(str(r["content"]), ""),
         "meh_count": int(r["meh_count"]), "users": int(r["users"])}
        for _, r in g.iterrows()
    ]


# ── domain-specific KPI sets ────────────────────────────────────

def _galaxy_kpis(df: pd.DataFrame, ua: pd.DataFrame, n_users: int, n_contents: int) -> list[dict]:
    """abtest framework `BaseKPIs` 기준만.
    archive 에 exposed 데이터 없어 CTR/CTRPU 는 측정 불가 → 제외.
    """
    n_events = int(len(df))
    return [
        {"label": "Total events",     "value": n_events,                    "fmt": "int"},
        {"label": "active_users",     "value": n_users,                     "fmt": "int"},
        {"label": "Unique contents",  "value": n_contents,                  "fmt": "int"},
        {"label": "UCPU",             "value": _ucpu(df, ua),               "fmt": "f2"},
        {"label": "총 RATE",          "value": int(ua["RATE"].sum()) if "RATE" in ua.columns else 0, "fmt": "int"},
        {"label": "총 WISH",          "value": int(ua["WISH"].sum()) if "WISH" in ua.columns else 0, "fmt": "int"},
        {"label": "총 CLICK",         "value": int(ua["CLICK"].sum()) if "CLICK" in ua.columns else 0, "fmt": "int"},
        {"label": "1인당 RATE",       "value": _per_user(ua, "RATE"),       "fmt": "f2"},
        {"label": "1인당 WISH",       "value": _per_user(ua, "WISH"),       "fmt": "f2"},
        {"label": "1인당 CLICK",      "value": _per_user(ua, "CLICK"),      "fmt": "f2"},
    ]


def _mars_kpis(df: pd.DataFrame, ua: pd.DataFrame, n_users: int, n_contents: int) -> list[dict]:
    """abtest framework `BaseKPIs` 기준만 (exposed 없어 CTR 제외)."""
    n_events = int(len(df))
    return [
        {"label": "Total events",     "value": n_events,                    "fmt": "int"},
        {"label": "active_users",     "value": n_users,                     "fmt": "int"},
        {"label": "Unique contents",  "value": n_contents,                  "fmt": "int"},
        {"label": "UCPU",             "value": _ucpu(df, ua),               "fmt": "f2"},
        {"label": "총 PLAY",          "value": int(ua["PLAY"].sum()) if "PLAY" in ua.columns else 0, "fmt": "int"},
        {"label": "총 WISH",          "value": int(ua["WISH"].sum()) if "WISH" in ua.columns else 0, "fmt": "int"},
        {"label": "총 RATE",          "value": int(ua["RATE"].sum()) if "RATE" in ua.columns else 0, "fmt": "int"},
        {"label": "총 CLICK",         "value": int(ua["CLICK"].sum()) if "CLICK" in ua.columns else 0, "fmt": "int"},
        {"label": "1인당 PLAY",       "value": _per_user(ua, "PLAY"),       "fmt": "f2"},
        {"label": "1인당 WISH",       "value": _per_user(ua, "WISH"),       "fmt": "f2"},
        {"label": "1인당 CLICK",      "value": _per_user(ua, "CLICK"),      "fmt": "f2"},
    ]


def _adult_kpis(df: pd.DataFrame, ua: pd.DataFrame, n_users: int, n_contents: int) -> list[dict]:
    """abtest framework `TvodKPIs` 기준만.
    REVENUE/AOV/ARPU 는 _adult_revenue() 에 별도 계산되어 'revenue' 필드로 노출.
    여기서는 BaseKPIs + CVR/CRPU/PUR (구매 전환).
    """
    n_events = int(len(df))
    rentals = int(ua["RENTAL"].sum()) if "RENTAL" in ua.columns else 0
    possessions = int(ua["POSSESSION"].sum()) if "POSSESSION" in ua.columns else 0
    purch_sum = rentals + possessions
    clicks = int(ua["CLICK"].sum()) if "CLICK" in ua.columns else 0
    # CRPU: per-user (purchase/click) → mean (abtest framework 정확 정의)
    if "CLICK" in ua.columns and len(ua):
        purch_per_user = (
            (ua.get("RENTAL", 0).astype(float) if "RENTAL" in ua.columns else 0)
            + (ua.get("POSSESSION", 0).astype(float) if "POSSESSION" in ua.columns else 0)
        )
        click_per_user = ua["CLICK"].astype(float)
        crpu_ratio = (purch_per_user / click_per_user).replace(
            [float("inf"), -float("inf")], 0
        ).fillna(0)
        crpu_val = float(crpu_ratio.mean())
    else:
        crpu_val = 0.0

    return [
        {"label": "Total events",   "value": n_events,                    "fmt": "int"},
        {"label": "active_users",   "value": n_users,                     "fmt": "int"},
        {"label": "Unique contents","value": n_contents,                  "fmt": "int"},
        {"label": "UCPU",           "value": _ucpu(df, ua),               "fmt": "f2"},
        {"label": "총 CLICK",       "value": clicks,                      "fmt": "int"},
        {"label": "총 RENTAL",      "value": rentals,                     "fmt": "int"},
        {"label": "총 POSSESSION",  "value": possessions,                 "fmt": "int"},
        {"label": "1인당 CLICK",    "value": _per_user(ua, "CLICK"),      "fmt": "f2"},
        {"label": "1인당 구매(R+P)","value": _safe_div(purch_sum, n_users), "fmt": "f2"},
        {"label": "CVR",            "value": _safe_div(purch_sum, clicks),"fmt": "pct"},
        {"label": "CRPU",           "value": crpu_val,                    "fmt": "pct"},
        # PUR per abtest = sum(rental+possession events) / active_users → 1인당 구매 횟수 (f2)
        {"label": "PUR",            "value": _safe_div(purch_sum, n_users), "fmt": "f2"},
    ]


def _kpis_from_ua(
    df: pd.DataFrame, ua: pd.DataFrame, domain: str, n_users: int, n_contents: int
) -> list[dict]:
    if domain == "galaxy": return _galaxy_kpis(df, ua, n_users, n_contents)
    if domain == "mars":   return _mars_kpis(df, ua, n_users, n_contents)
    if domain == "adult":  return _adult_kpis(df, ua, n_users, n_contents)
    return []


def _kpis(df: pd.DataFrame, domain: str) -> list[dict]:
    if df.empty: return []
    ua = _user_action_pivot(df)
    return _kpis_from_ua(df, ua, domain, len(ua), int(df["content"].nunique()))


def _kpi_series(df: pd.DataFrame, domain: str, overall: list[dict]) -> tuple[list[str], dict[str, list[float]]]:
    """일자별 KPI 값 시계열 — sparkline / 일별 트렌드용.

    Performance: 7번 .groupby() 대신 한 번에 (date, user, action) 으로 묶어
    MultiIndex pivot 을 만든 뒤 xs() 로 daily slice 한다.  ~2-3x 빠르다."""
    if df.empty:
        return [], {}
    dates = sorted(df["date"].unique().tolist())
    series: dict[str, list[float]] = {k["label"]: [] for k in overall}

    # Single big groupby: (date, user, action) → count, then unstack actions
    daily_events = (
        df.groupby(["date", "user_id", "action_type"], observed=True, sort=False)
        .size()
        .unstack("action_type", fill_value=0)
    )
    # Per-day content nunique / rating mean 용. dict(list(groupby)) 로 30일치를
    # 동시에 들고 있으면 MARS(25M행) 에서 peak 메모리 스파이크 → groupby 객체에서
    # get_group 으로 한 번에 한 일자만 materialize (loop 끝나면 GC).
    grp = df.groupby("date", observed=True, sort=False)
    empty_df = df.iloc[0:0]

    for d in dates:
        sub_ua = daily_events.xs(d, level="date")
        try:
            sub_df = grp.get_group(d)
        except KeyError:
            sub_df = empty_df
        if len(sub_ua) == 0:
            for label in series: series[label].append(0)
            continue
        n_users_d = len(sub_ua)
        n_contents_d = int(sub_df["content"].nunique())
        daily = _kpis_from_ua(sub_df, sub_ua, domain, n_users_d, n_contents_d)
        daily_map = {k["label"]: k["value"] for k in daily}
        for label in series:
            series[label].append(daily_map.get(label, 0))
    return dates, series


# ── shared aggregations ─────────────────────────────────────────

def _timeseries(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    g = df.groupby("date").agg(
        events=("user_id", "size"),
        users=("user_id", "nunique"),
    ).reset_index()
    return [
        {"date": r["date"], "events": int(r["events"]), "users": int(r["users"])}
        for _, r in g.iterrows()
    ]


def _action_breakdown(df: pd.DataFrame) -> list[dict]:
    if df.empty or "action_type" not in df.columns:
        return []
    s = df["action_type"].astype(str).value_counts()
    return [{"label": str(k), "count": int(v)} for k, v in s.items()]


def _top_contents(df: pd.DataFrame, n: int = 10) -> list[dict]:
    if df.empty or "content" not in df.columns:
        return []
    g = (
        df.groupby("content", observed=True)
        .agg(events=("user_id", "size"), users=("user_id", "nunique"))
        .sort_values("events", ascending=False)
        .head(n)
        .reset_index()
    )
    tm = _load_title_map()
    return [
        {"content": str(r["content"]), "title": tm.get(str(r["content"]), ""),
         "events": int(r["events"]), "users": int(r["users"])}
        for _, r in g.iterrows()
    ]


# ── public API ──────────────────────────────────────────────────

def domain_meta() -> list[dict]:
    return [{"key": k, "label": v} for k, v in DOMAIN_LABEL.items()]


def available_range(domain: str) -> dict:
    specs = _domain_files(domain)
    if not specs:
        return {"min": None, "max": None}
    return {
        "min": min(s.start for s in specs).isoformat(),
        "max": max(s.end for s in specs).isoformat(),
    }


def available_range_dates(domain: str) -> tuple[date | None, date | None]:
    """Parsed (min, max) as date objects, or (None, None) if no archive data.

    Callers must handle the None case (e.g. CI / 아카이브 미마운트 환경) —
    avoids `date.fromisoformat(None)` TypeError at every range-consuming site.
    """
    rng = available_range(domain)
    if not rng["min"] or not rng["max"]:
        return None, None
    return date.fromisoformat(rng["min"]), date.fromisoformat(rng["max"])


def _load_filtered(
    domain: str,
    start: date,
    end: date,
    content_types: list[str] | None,
    action_types: list[str] | None = None,
) -> tuple[pd.DataFrame, list[FileSpec]]:
    picks = _pick_files(_domain_files(domain), start, end)
    df = _load(picks, start, end, domain)
    # content_types filter (galaxy & mars)
    ct_options = (GALAXY_CONTENT_TYPES if domain == "galaxy"
                  else MARS_CONTENT_TYPES if domain == "mars" else [])
    if content_types and ct_options and "content_type" in df.columns:
        mapping = {ct["key"]: ct["value"] for ct in ct_options}
        selected = [mapping[c] for c in content_types if c in mapping]
        if selected:
            df = df[df["content_type"].isin(selected)]
    # action_types filter (모든 도메인)
    if action_types and "action_type" in df.columns:
        df = df[df["action_type"].astype(str).isin(action_types)]
    return df, picks


def summary(
    domain: str,
    start: date,
    end: date,
    content_types: list[str] | None = None,
    action_types: list[str] | None = None,
) -> dict:
    """fast path — 카드 / 표 값 / 시계열 / 액션 / TOP10.

    응답 dict 자체를 LRU cache (RESULT_CACHE) 하므로 같은 query 재호출 시 즉시 hit."""
    cache_key = ("summary", domain, start.isoformat(), end.isoformat(),
                 tuple(content_types or []), tuple(action_types or []))
    hit = _cache_get(cache_key)
    if hit is not None:
        return hit
    t0 = time.time()
    df, picks = _load_filtered(domain, start, end, content_types, action_types)
    overall = _kpis(df, domain)
    result = {
        "domain": domain,
        "label": DOMAIN_LABEL.get(domain, domain),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "content_types": content_types or [],
        "action_types": action_types or [],
        "available_content_types": (
            GALAXY_CONTENT_TYPES if domain == "galaxy"
            else MARS_CONTENT_TYPES if domain == "mars"
            else []
        ),
        "available_action_types": ACTION_TYPES.get(domain, []),
        "hero_labels": HERO_LABELS.get(domain, []),
        "table_priority": TABLE_PRIORITY.get(domain, []),
        "kpis": overall,
        "timeseries": _timeseries(df),
        "actions": _action_breakdown(df),
        "top_contents": _top_contents(df),
        "top_genres": _top_genres(df, domain),
        "content_type_breakdown": _content_type_breakdown(df),
        "rating_distribution": _rating_distribution(df, domain, start, end, content_types),
        "hourly_activity": _hourly_activity(df),
        "pareto_curve": _pareto_curve(df),
        "revenue": (
            _adult_revenue(df, domain) if domain == "adult"
            else _mars_revenue(start, end) if domain == "mars"
            else {"available": False}
        ),
        "top_actors": (
            _adult_meta_top(df, domain, "actor") if domain == "adult"
            else _galaxy_mars_meta_top(df, "actor") if domain in ("galaxy", "mars")
            else []
        ),
        "top_directors": (
            _adult_meta_top(df, domain, "director") if domain == "adult"
            else _galaxy_mars_meta_top(df, "director") if domain in ("galaxy", "mars")
            else []
        ),
        "top_revenue_contents": (
            _adult_top_revenue_contents(df, domain) if domain == "adult"
            else _mars_top_revenue_contents(start, end) if domain == "mars"
            else []
        ),
        "top_rated_contents": _top_rated_contents(df, domain),
        "top_meh_contents": _top_meh_contents(domain, start, end),
        "top_users": _top_users(df, domain),
        "supports": SUPPORTS.get(domain, {}),
        "supports_genre": domain in GENRE_DOMAINS,
        "files_read": [Path(s.path).name for s in picks],
        "elapsed_ms": int((time.time() - t0) * 1000),
    }
    _cache_put(cache_key, result)
    return result


def series_response(
    domain: str,
    start: date,
    end: date,
    content_types: list[str] | None = None,
    action_types: list[str] | None = None,
    label: str | None = None,
) -> dict:
    """일자별 KPI series. label 지정 시 해당 KPI 만 (모달 디테일용).

    full series 결과를 LRU cache 해서 같은 query 재호출 시 즉시 hit.
    단일 label 요청은 cached full series 에서 slice."""
    full_key = ("series", domain, start.isoformat(), end.isoformat(),
                tuple(content_types or []), tuple(action_types or []))
    full = _cache_get(full_key)
    if full is None:
        t0 = time.time()
        df, _ = _load_filtered(domain, start, end, content_types, action_types)
        overall = _kpis(df, domain)
        dates, series = _kpi_series(df, domain, overall)
        fmt_by_label = {k["label"]: k["fmt"] for k in overall}
        val_by_label = {k["label"]: k["value"] for k in overall}
        full = {
            "dates": dates,
            "fmts": fmt_by_label,
            "series": series,
            "_vals": val_by_label,
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
        _cache_put(full_key, full)

    if label:
        if label not in full["series"]:
            raise KeyError(label)
        return {
            "dates": full["dates"],
            "label": label,
            "fmt": full["fmts"].get(label, "int"),
            "total": full["_vals"].get(label, 0),
            "values": full["series"][label],
            "elapsed_ms": full["elapsed_ms"],
        }
    return {
        "dates": full["dates"],
        "fmts": full["fmts"],
        "series": full["series"],
        "elapsed_ms": full["elapsed_ms"],
    }
