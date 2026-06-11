"""Unit tests for mars_adultplus_summary processor.

BQ fetch 자체는 google-cloud-bigquery + IRSA 가 필요해 unit 테스트 안 함.
processor (groupby / ratio / top-N) 는 fetcher mock 으로 검증.
"""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _sample_cs_df():
    """fetch_mars_kpi_tod_adultplus 모의 출력 — 3일치 × 2 titles."""
    return pd.DataFrame([
        # day 1
        {"remy_date": date(2026, 6, 1), "content": "16:1001", "title": "A",
         "served": 100, "exposed": 80, "clicked": 16, "played": 8,
         "wished": 2, "meh": 1, "purchased": 4},
        {"remy_date": date(2026, 6, 1), "content": "16:1002", "title": "B",
         "served": 100, "exposed": 60, "clicked": 6, "played": 3,
         "wished": 0, "meh": 0, "purchased": 1},
        # day 2
        {"remy_date": date(2026, 6, 2), "content": "16:1001", "title": "A",
         "served": 120, "exposed": 100, "clicked": 20, "played": 10,
         "wished": 3, "meh": 1, "purchased": 5},
        {"remy_date": date(2026, 6, 2), "content": "16:1002", "title": "B",
         "served": 100, "exposed": 70, "clicked": 7, "played": 4,
         "wished": 1, "meh": 0, "purchased": 2},
    ])


def _sample_meta_df():
    return pd.DataFrame([{
        "total_recommends": 42000,
        "unique_users": 7500,
        "elapsed_median_ms": 10.5,
    }])


def _empty_cs_df():
    return pd.DataFrame(columns=[
        "remy_date", "content", "title", "served", "exposed",
        "clicked", "played", "wished", "meh", "purchased",
    ])


def _sample_rs_df():
    """fetch_mars_kpi_tod_adultplus_rs 모의 — 2일 × 3 rs.keys."""
    return pd.DataFrame([
        {"remy_date": date(2026, 6, 1), "key": "titledRecommend",
         "rs_served": 1500, "rs_exposed": 1000, "rs_clicked": 230, "rs_action_cells": 70},
        {"remy_date": date(2026, 6, 1), "key": "preview",
         "rs_served": 900, "rs_exposed": 800, "rs_clicked": 200, "rs_action_cells": 50},
        {"remy_date": date(2026, 6, 2), "key": "titledRecommend",
         "rs_served": 1800, "rs_exposed": 1200, "rs_clicked": 290, "rs_action_cells": 90},
    ])


def _sample_users_daily_df():
    return pd.DataFrame([
        {"remy_date": date(2026, 6, 1), "unique_users": 1100, "total_recommends": 6500},
        {"remy_date": date(2026, 6, 2), "unique_users": 1200, "total_recommends": 7000},
    ])


def _empty_rs_df():
    return pd.DataFrame(columns=[
        "remy_date", "key", "rs_served", "rs_exposed", "rs_clicked", "rs_action_cells",
    ])


def _empty_users_df():
    return pd.DataFrame(columns=["remy_date", "unique_users", "total_recommends"])


def _patch_all(cs, rs=None, users=None, meta=None):
    """Helper — patch 4 fetchers at once."""
    return [
        patch("data_sources.bq.fetch_mars_kpi_tod_adultplus", return_value=cs),
        patch("data_sources.bq.fetch_mars_kpi_tod_adultplus_rs",
              return_value=rs if rs is not None else _empty_rs_df()),
        patch("data_sources.bq.fetch_mars_kpi_tod_adultplus_users_daily",
              return_value=users if users is not None else _empty_users_df()),
        patch("data_sources.bq.fetch_mars_kpi_tod_adultplus_meta",
              return_value=meta if meta is not None else _sample_meta_df()),
    ]


def _enter_all(patches):
    # 캐시 잔존 방지 — 매 호출 시 초기화 (테스트 간 cross-talk 차단)
    import kpi
    kpi._AP_CACHE.clear()
    for p in patches: p.start()
    return patches


# ── mars_adultplus_summary ───────────────────────────────────────────────
def test_mars_adultplus_summary_hero_ratios():
    """Hero 의 click/play/purchase ratio 가 sum(c)/sum(exposed) 인지."""
    import kpi
    patches = _patch_all(_sample_cs_df(), _sample_rs_df(), _sample_users_daily_df())
    try:
        _enter_all(patches)
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 2))
    finally:
        for p in patches: p.stop()

    # totals (cs)
    assert r["totals"]["exposed"] == 80 + 60 + 100 + 70  # 310
    assert r["totals"]["clicked"] == 16 + 6 + 20 + 7  # 49
    assert r["totals"]["purchased"] == 4 + 1 + 5 + 2  # 12
    # totals (rs)
    assert r["totals"]["rs_exposed"] == 1000 + 800 + 1200  # 3000
    assert r["totals"]["rs_clicked"] == 230 + 200 + 290  # 720

    # hero ratios
    assert r["hero"]["click_ratio"] == round(49 / 310, 4)
    assert r["hero"]["purchase_ratio"] == round(12 / 310, 4)
    assert r["hero"]["rows_click_ratio"] == round(720 / 3000, 4)
    # hero meta
    assert r["hero"]["unique_users"] == 7500


def test_mars_adultplus_summary_timeseries_daily():
    """timeseries 가 날짜별 + cs/rs/users 결합."""
    import kpi
    patches = _patch_all(_sample_cs_df(), _sample_rs_df(), _sample_users_daily_df())
    try:
        _enter_all(patches)
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 2))
    finally:
        for p in patches: p.stop()
    ts = r["timeseries"]
    assert len(ts) == 2
    assert ts[0]["date"] == "2026-06-01"
    assert ts[0]["exposed"] == 80 + 60  # cs
    assert ts[0]["rs_exposed"] == 1000 + 800  # rs
    assert ts[0]["unique_users"] == 1100  # users
    assert ts[0]["rs_click_ratio"] == round(430 / 1800, 4)


def test_mars_adultplus_summary_rows_pie():
    """rs.key 별 pie 산출 — exposed/clicked/actions 3종."""
    import kpi
    patches = _patch_all(_sample_cs_df(), _sample_rs_df(), _sample_users_daily_df())
    try:
        _enter_all(patches)
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 2))
    finally:
        for p in patches: p.stop()
    pies = r["rows_pie"]
    assert len(pies["exposed"]) == 2
    # titledRecommend 가 1순위 (1000+1200=2200)
    assert pies["exposed"][0]["key"] == "titledRecommend"
    assert pies["exposed"][0]["value"] == 2200
    # clicked 도 titledRecommend 가 1순위 (230+290=520)
    assert pies["clicked"][0]["key"] == "titledRecommend"
    assert pies["clicked"][0]["value"] == 520


def test_mars_adultplus_summary_top_titles_sorted_by_exposed():
    """top_titles 가 exposed 기준 desc 정렬 + click_ratio 포함."""
    import kpi
    patches = _patch_all(_sample_cs_df(), _sample_rs_df(), _sample_users_daily_df())
    try:
        _enter_all(patches)
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 2), top_n=10)
    finally:
        for p in patches: p.stop()
    tops = r["top_titles"]
    assert len(tops) == 2
    # Title A: exposed 180 (80+100), clicked 36 (16+20)
    assert tops[0]["title"] == "A"
    assert tops[0]["exposed"] == 180
    assert tops[0]["click_ratio"] == round(36 / 180, 4)
    # Title B: exposed 130
    assert tops[1]["title"] == "B"
    assert tops[1]["exposed"] == 130


def test_mars_adultplus_summary_top_n_limit():
    """top_n=1 일 때 1개만 반환."""
    import kpi
    patches = _patch_all(_sample_cs_df(), _sample_rs_df(), _sample_users_daily_df())
    try:
        _enter_all(patches)
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 2), top_n=1)
    finally:
        for p in patches: p.stop()
    assert len(r["top_titles"]) == 1
    assert r["top_titles"][0]["title"] == "A"


def test_mars_adultplus_summary_empty_data():
    """BQ 가 빈 결과 반환 시 0 hero / 빈 ts / 빈 pies / 빈 titles."""
    import kpi
    patches = _patch_all(_empty_cs_df(), _empty_rs_df(), _empty_users_df(),
                         pd.DataFrame())
    try:
        _enter_all(patches)
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 2))
    finally:
        for p in patches: p.stop()
    assert r["hero"]["unique_users"] == 0
    assert r["hero"]["click_ratio"] == 0.0
    assert r["hero"]["rows_click_ratio"] == 0.0
    assert r["timeseries"] == []
    assert r["rows_pie"]["exposed"] == []
    assert r["top_titles"] == []


def test_mars_adultplus_summary_window_validation():
    """start > end 시 ValueError (다른 KPI 와 동일 가드)."""
    import kpi
    with pytest.raises(ValueError):
        kpi.mars_adultplus_summary(date(2026, 6, 5), date(2026, 6, 1))


def test_mars_adultplus_summary_zero_exposed_no_division_error():
    """exposed=0 일 때 ratio division-by-zero 안 나는지."""
    import kpi
    df_zero = pd.DataFrame([{
        "remy_date": date(2026, 6, 1), "content": "16:1", "title": "T",
        "served": 100, "exposed": 0, "clicked": 0, "played": 0,
        "wished": 0, "meh": 0, "purchased": 0,
    }])
    patches = _patch_all(df_zero, _empty_rs_df(), _empty_users_df())
    try:
        _enter_all(patches)
        r = kpi.mars_adultplus_summary(date(2026, 6, 1), date(2026, 6, 1))
    finally:
        for p in patches: p.stop()
    assert r["hero"]["click_ratio"] == 0.0
    assert r["top_titles"][0]["click_ratio"] == 0.0
