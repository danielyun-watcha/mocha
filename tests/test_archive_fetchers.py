"""Smoke tests for `data_sources/archive.py`.

Real archive (`/archive/mocha/*`) 는 prod-mount 환경에만 있으므로
tmp_path fixture 에 mock feather 를 작성하고 `MEHS_PATH` /
`MARS_TVOD_PURCHASES_PATH` 모듈 변수를 monkeypatch 하는 방식.

검증 포인트:
- KST window filter — start KST 자정 ≤ t < (end+1) KST 자정
- 결과 schema (컬럼/dtype) — 호출자 (kpi.py) 가 의존
- 파일 부재 시 FileNotFoundError
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from data_sources import archive

KST = timezone(timedelta(hours=9))


def _ts(d: str, h: int = 12) -> int:
    """KST date string → unix sec at given hour."""
    y, m, day = map(int, d.split("-"))
    return int(datetime(y, m, day, h, tzinfo=KST).timestamp())


# ── read_mehs ───────────────────────────────────────────────────────────


@pytest.fixture
def mehs_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """3 row mock — 1 inside, 1 before, 1 after the test window."""
    df = pd.DataFrame({
        "user_id":      [10, 11, 12],
        "content_type": [1, 2, 4],
        "content":      ["1:100", "2:200", "4:300"],
        "action_type":  [3, 3, 3],
        "value":        [0, 0, 0],
        "timestamp":    [
            _ts("2026-05-19", 23),  # 윈도우 직전 (5/20 자정 -1h)
            _ts("2026-05-22", 10),  # 윈도우 안
            _ts("2026-05-27", 5),   # 윈도우 직후 (5/26 23:59 이후)
        ],
    })
    p = tmp_path / "mehs.ftr"
    df.to_feather(p)
    monkeypatch.setattr(archive, "MEHS_PATH", p)
    return p


def test_read_mehs_window_filter(mehs_fixture):
    df = archive.read_mehs(date(2026, 5, 20), date(2026, 5, 26))
    # 윈도우 안 1 row 만
    assert len(df) == 1
    assert df["user_id"].iloc[0] == 11


def test_read_mehs_schema(mehs_fixture):
    df = archive.read_mehs(date(2026, 5, 20), date(2026, 5, 26))
    assert list(df.columns) == [
        "user_id", "content", "content_type", "action_type", "created_at",
    ]
    # action_type 은 항상 "MEH" 문자열로 정규화
    assert (df["action_type"] == "MEH").all()


def test_read_mehs_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MEHS_PATH", tmp_path / "nonexistent.ftr")
    with pytest.raises(FileNotFoundError):
        archive.read_mehs(date(2026, 5, 20), date(2026, 5, 26))


# ── read_mars_tvod_purchases ────────────────────────────────────────────


@pytest.fixture
def tvod_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    df = pd.DataFrame({
        "user_id":      [100, 101, 102],
        "content_type": [1, 128, 16],
        "content":      ["1:5", "128:50", "16:1"],
        "action_type":  ["rental", "possession", "rental"],
        "timestamp":    [
            _ts("2026-05-22", 10),   # in window
            _ts("2026-05-25", 14),   # in window
            _ts("2026-05-28", 10),   # out
        ],
        "amount_cents": [5000, 12000, 3000],
    })
    p = tmp_path / "mars_tvod_purchases.ftr"
    df.to_feather(p)
    monkeypatch.setattr(archive, "MARS_TVOD_PURCHASES_PATH", p)
    return p


def test_read_mars_tvod_purchases_window(tvod_fixture):
    df = archive.read_mars_tvod_purchases(date(2026, 5, 20), date(2026, 5, 26))
    assert len(df) == 2
    assert set(df["user_id"]) == {100, 101}


def test_read_mars_tvod_purchases_schema(tvod_fixture):
    df = archive.read_mars_tvod_purchases(date(2026, 5, 20), date(2026, 5, 26))
    assert list(df.columns) == [
        "user_id", "content", "content_type", "action_type",
        "created_at", "amount_cents",
    ]


def test_read_mars_tvod_purchases_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "MARS_TVOD_PURCHASES_PATH", tmp_path / "x.ftr")
    with pytest.raises(FileNotFoundError):
        archive.read_mars_tvod_purchases(date(2026, 5, 20), date(2026, 5, 26))


# ── _kst_window_unix ────────────────────────────────────────────────────


def test_kst_window_inclusive_start_exclusive_end():
    start_ts, end_ts = archive._kst_window_unix(
        date(2026, 5, 20), date(2026, 5, 26),
    )
    # 5/20 00:00 KST <= t < 5/27 00:00 KST
    assert start_ts == _ts("2026-05-20", 0)
    assert end_ts == _ts("2026-05-27", 0)
