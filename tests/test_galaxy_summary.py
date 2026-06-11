"""Galaxy funnel summary tests — archive 기반 PDF-style schema 산출.

mars_adultplus_summary 와 동일한 응답 구조 (hero/timeseries/rows_pie/rows_table/
top_titles/ctype_pie) 를 archive 데이터 (RATE/WISH/SEARCH/CLICK) 로 채움.
"""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Galaxy 의 action_type code 매핑 (CLAUDE.md):
#   1=RATE, 2=WISH, 6=SEARCH, 7=CLICK
ACTION_RATE = "RATE"
ACTION_WISH = "WISH"
ACTION_SEARCH = "SEARCH"
ACTION_CLICK = "CLICK"


def _sample_galaxy_events():
    """archive read mock — galaxy behavior 이벤트.

    하루 = 4 actions × 2 contents. 총 8건.
    """
    rows = []
    for d in (date(2026, 6, 1), date(2026, 6, 2)):
        ts = int(pd.Timestamp(d).timestamp()) + 12 * 3600  # KST 정오
        # content 1 (Movie, content="1:100"): RATE 1, WISH 2, SEARCH 0, CLICK 3
        rows.append({"user_id": 1, "content": "1:100", "content_type": 1,
                     "created_at": ts, "action_type": ACTION_RATE, "value": 8})
        rows.append({"user_id": 2, "content": "1:100", "content_type": 1,
                     "created_at": ts, "action_type": ACTION_WISH, "value": 0})
        rows.append({"user_id": 3, "content": "1:100", "content_type": 1,
                     "created_at": ts, "action_type": ACTION_WISH, "value": 0})
        rows.extend([{"user_id": 4 + i, "content": "1:100", "content_type": 1,
                      "created_at": ts, "action_type": ACTION_CLICK, "value": 0}
                     for i in range(3)])
        # content 2 (TvSeason, content="2:200"): RATE 1, SEARCH 2
        rows.append({"user_id": 1, "content": "2:200", "content_type": 2,
                     "created_at": ts, "action_type": ACTION_RATE, "value": 10})
        rows.extend([{"user_id": 8 + i, "content": "2:200", "content_type": 2,
                      "created_at": ts, "action_type": ACTION_SEARCH, "value": 0}
                     for i in range(2)])
    return pd.DataFrame(rows)


# ── Schema 일치 ─────────────────────────────────────────────────────────
def test_galaxy_summary_returns_pdf_schema():
    """mars_adultplus_summary 와 동일한 응답 키 구조."""
    import kpi
    with patch.object(kpi, "_read_galaxy_archive",
                      return_value=_sample_galaxy_events(), create=True):
        r = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
    # 최상위 키 일치
    expected_keys = {"domain", "period", "hero", "timeseries", "rows_pie",
                     "rows_table", "top_titles", "ctype_pie", "totals", "from_cache"}
    assert set(r.keys()) >= expected_keys
    # hero 의 핵심 필드
    for k in ("total_recommends", "unique_users", "rows_click_ratio",
              "cells_action_ratio", "click_ratio"):
        assert k in r["hero"]


def test_galaxy_summary_counts_total_events():
    """hero.total_recommends = archive 행 수 (= 이벤트 수)."""
    import kpi
    df = _sample_galaxy_events()
    with patch.object(kpi, "_read_galaxy_archive", return_value=df, create=True):
        r = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
    # 하루 9건 (content1: 1+2+3=6, content2: 1+2=3) × 2일 = 18
    assert r["hero"]["total_recommends"] == 18


def test_galaxy_summary_unique_users():
    """hero.unique_users = distinct user_id."""
    import kpi
    df = _sample_galaxy_events()
    with patch.object(kpi, "_read_galaxy_archive", return_value=df, create=True):
        r = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
    # 유저: 1,2,3,4,5,6,1,8,9 → distinct {1,2,3,4,5,6,8,9} = 8
    assert r["hero"]["unique_users"] == 8


def test_galaxy_summary_click_ratio():
    """click_ratio = CLICK events / 전체 events."""
    import kpi
    df = _sample_galaxy_events()
    with patch.object(kpi, "_read_galaxy_archive", return_value=df, create=True):
        r = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
    # CLICK: 하루 3건 × 2일 = 6. 전체 18. → 6/18 ≈ 0.3333
    assert r["hero"]["click_ratio"] == round(6 / 18, 4)


def test_galaxy_summary_rows_pie_by_action():
    """rows_pie.exposed / clicked 등 — action_type 기준 분포."""
    import kpi
    df = _sample_galaxy_events()
    with patch.object(kpi, "_read_galaxy_archive", return_value=df, create=True):
        r = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
    rp = r["rows_pie"]
    # action 별 키가 들어 있는지
    exposed_keys = {p["key"] for p in rp["exposed"]}
    assert {"RATE", "WISH", "SEARCH", "CLICK"} & exposed_keys


def test_galaxy_summary_ctype_pie():
    """ctype_pie — content_type prefix 기준."""
    import kpi
    df = _sample_galaxy_events()
    with patch.object(kpi, "_read_galaxy_archive", return_value=df, create=True):
        r = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
    # Movie (1) 와 TvSeason (2) 둘 다 등장
    ct_keys = {p["key"] for p in r["ctype_pie"]}
    assert "Movie" in ct_keys
    assert "TvSeason" in ct_keys


def test_galaxy_summary_timeseries_daily():
    """timeseries 가 날짜별로 묶이고 cs 컬럼 키 포함."""
    import kpi
    df = _sample_galaxy_events()
    with patch.object(kpi, "_read_galaxy_archive", return_value=df, create=True):
        r = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
    ts = r["timeseries"]
    assert len(ts) == 2
    # cs 호환 컬럼 존재
    for k in ("served", "exposed", "clicked", "wished", "rs_clicked"):
        assert k in ts[0]


def test_galaxy_summary_top_titles_present():
    """top_titles — content/title 별 TOP N."""
    import kpi
    df = _sample_galaxy_events()
    with patch.object(kpi, "_read_galaxy_archive", return_value=df, create=True):
        r = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2), top_n=5)
    assert len(r["top_titles"]) <= 5
    # 컬럼 형태 mars/adult 와 동일
    if r["top_titles"]:
        for k in ("content", "title", "served", "exposed", "clicked", "click_ratio"):
            assert k in r["top_titles"][0]


def test_galaxy_summary_window_validation():
    """start > end 시 ValueError."""
    import kpi
    with pytest.raises(ValueError):
        kpi.galaxy_summary(date(2026, 6, 5), date(2026, 6, 1))


def test_galaxy_summary_cache():
    """galaxy_summary 도 cache 적용 (같은 cache 인프라 공유)."""
    import kpi
    kpi._AP_CACHE.clear()
    df = _sample_galaxy_events()
    with patch.object(kpi, "_read_galaxy_archive", return_value=df, create=True):
        r1 = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
        r2 = kpi.galaxy_summary(date(2026, 6, 1), date(2026, 6, 2))
    assert r1["from_cache"] is False
    assert r2["from_cache"] is True
