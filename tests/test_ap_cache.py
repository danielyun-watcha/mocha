"""AdultPlus / SVOD / TVOD / Galaxy summary cache (in-memory LRU + TTL) tests.

기능: 같은 (table_kind, start, end, top_n, filters) 호출 시 ⚡ cache hit.
TTL 만료 / force=True / LRU max 도달 시 cache 동작 검증.
"""
import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))


def _make_min_cs_df():
    return pd.DataFrame([{
        "remy_date": date(2026, 6, 1), "content": "16:1", "title": "T",
        "served": 100, "exposed": 80, "clicked": 16, "played": 8,
        "wished": 2, "meh": 1, "purchased": 4,
    }])


def _make_min_rs_df():
    return pd.DataFrame([{
        "remy_date": date(2026, 6, 1), "key": "titledRecommend",
        "rs_served": 100, "rs_exposed": 80, "rs_clicked": 16, "rs_action_cells": 20,
    }])


def _make_min_users_df():
    return pd.DataFrame([{
        "remy_date": date(2026, 6, 1), "unique_users": 50, "total_recommends": 200,
    }])


def _make_min_meta_df():
    return pd.DataFrame([{
        "total_recommends": 200, "unique_users": 50, "elapsed_median_ms": 10.0,
    }])


def _patch_fetchers(cs, rs, users, meta):
    return [
        patch("data_sources.bq.fetch_mars_kpi_tod_adultplus", return_value=cs),
        patch("data_sources.bq.fetch_mars_kpi_tod_adultplus_rs", return_value=rs),
        patch("data_sources.bq.fetch_mars_kpi_tod_adultplus_users_daily", return_value=users),
        patch("data_sources.bq.fetch_mars_kpi_tod_adultplus_meta", return_value=meta),
    ]


def _start_all(patches):
    for p in patches: p.start()


def _stop_all(patches):
    for p in patches: p.stop()


def _clear_cache():
    import kpi
    kpi._AP_CACHE.clear()


# ── Basic cache hit / miss ──────────────────────────────────────────────
def test_first_call_is_miss():
    """첫 호출은 cache miss → from_cache=False, fetchers 호출됨."""
    import kpi
    _clear_cache()
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
        assert r["from_cache"] is False
    finally:
        _stop_all(patches)


def test_second_call_same_args_is_cache_hit():
    """같은 인자로 두 번째 호출 → from_cache=True, fetchers 호출 안 됨."""
    import kpi
    _clear_cache()
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        # 첫 호출
        kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
        # fetcher 호출 횟수 reset 위해 mock 의 reset_mock
        for p in patches:
            p.target.__dict__[p.attribute].reset_mock()
        # 두 번째 호출
        r2 = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
        assert r2["from_cache"] is True
        # fetcher 가 다시 호출되지 않았는지
        for p in patches:
            mock_fn = p.target.__dict__[p.attribute]
            assert mock_fn.call_count == 0, f"{p.attribute} called {mock_fn.call_count} times"
    finally:
        _stop_all(patches)


def test_force_bypasses_cache():
    """force=True → cache 무시하고 다시 fetch."""
    import kpi
    _clear_cache()
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
        r2 = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1), force=True)
        # force=True 면 from_cache False (재계산)
        assert r2["from_cache"] is False
    finally:
        _stop_all(patches)


def test_different_table_kinds_have_separate_cache():
    """svod / tvod_all / tvod_adultplus 캐시 분리."""
    import kpi
    _clear_cache()
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        r_ap = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1),
                                          table_kind="tvod_adultplus")
        r_svod = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1),
                                            table_kind="svod")
        # 둘 다 첫 호출 → 모두 from_cache=False
        assert r_ap["from_cache"] is False
        assert r_svod["from_cache"] is False
        # 두 번째 호출 → 각자 cache hit
        r_ap2 = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1),
                                           table_kind="tvod_adultplus")
        assert r_ap2["from_cache"] is True
    finally:
        _stop_all(patches)


def test_different_filters_have_separate_cache():
    """필터 다르면 별도 cache key."""
    import kpi
    _clear_cache()
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1), filters={"client": "1"})
        r2 = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1), filters={"client": "2"})
        assert r2["from_cache"] is False  # 다른 filter — 새 fetch
    finally:
        _stop_all(patches)


def test_empty_filter_keys_normalized():
    """filters={"client": None} 과 filters={} 가 같은 cache key."""
    import kpi
    _clear_cache()
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1),
                                   filters={"client": None, "country": ""})
        r2 = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1), filters={})
        assert r2["from_cache"] is True  # 빈 값 정규화로 같은 key
    finally:
        _stop_all(patches)


# ── TTL 동작 ─────────────────────────────────────────────────────────────
def test_ttl_expired_triggers_refetch(monkeypatch):
    """TTL 초과 → cache miss → 재 fetch."""
    import kpi
    _clear_cache()
    # 매우 짧은 TTL 시뮬레이션
    monkeypatch.setattr(kpi, "_AP_CACHE_TTL", 0)  # 0초 = 즉시 만료
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
        time.sleep(0.01)  # 0초 TTL → 즉시 만료
        r2 = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
        assert r2["from_cache"] is False
    finally:
        _stop_all(patches)


# ── LRU eviction ─────────────────────────────────────────────────────────
def test_lru_eviction_at_max(monkeypatch):
    """캐시 max 도달 시 LRU 가장 오래 사용 안 한 entry evict.

    순서:
      1) put (6,1) → cache: [6,1]
      2) put (6,2) → cache: [6,1, 6,2]
      3) put (6,3) → size>max, evict oldest (6,1) → cache: [6,2, 6,3]
      4) get (6,3) → hit + LRU touch → cache: [6,2, 6,3] (6,3 moved to end)
      5) get (6,2) → hit → cache: [6,3, 6,2]
      6) get (6,1) → miss (evicted in step 3) + 다시 put → evict oldest (6,3)
    """
    import kpi
    _clear_cache()
    monkeypatch.setattr(kpi, "_AP_CACHE_MAX", 2)
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))  # 1
        kpi.mars_adultplus_summary(date(2026, 6, 2), date(2026, 6, 2))  # 2
        kpi.mars_adultplus_summary(date(2026, 6, 3), date(2026, 6, 3))  # 3 → evict (6,1)
        # (6,3) cache hit
        r3 = kpi.mars_adultplus_summary(date(2026, 6, 3), date(2026, 6, 3))
        assert r3["from_cache"] is True
        # (6,2) cache hit
        r2 = kpi.mars_adultplus_summary(date(2026, 6, 2), date(2026, 6, 2))
        assert r2["from_cache"] is True
        # (6,1) miss (evicted)
        r1 = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
        assert r1["from_cache"] is False
    finally:
        _stop_all(patches)


# ── Prewarm 동작 ─────────────────────────────────────────────────────────
def test_prewarm_populates_cache():
    """prewarm 호출 후 같은 인자로 다시 호출하면 cache hit."""
    import kpi
    _clear_cache()
    patches = _patch_fetchers(_make_min_cs_df(), _make_min_rs_df(),
                              _make_min_users_df(), _make_min_meta_df())
    try:
        _start_all(patches)
        # prewarm 호출 (force=True 로 보수적으로)
        kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1), force=True)
        # 사용자 첫 호출 시 cache hit
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
        assert r["from_cache"] is True
    finally:
        _stop_all(patches)
