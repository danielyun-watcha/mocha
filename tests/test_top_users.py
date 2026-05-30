"""Unit tests for `kpi._top_users` — 도메인별 활동/소비 TOP N user ranking.

Pure DataFrame in / list-of-dict out — no I/O.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from kpi import _top_users


def _df(rows: list[tuple]) -> pd.DataFrame:
    """Helper — rows = [(user_id, action_type, content)]"""
    return pd.DataFrame(rows, columns=["user_id", "action_type", "content"])


# ── galaxy: 총 액션 수 ────────────────────────────────────────────────


def test_galaxy_orders_by_total_events():
    df = _df([
        (1, "CLICK", "1:1"), (1, "CLICK", "1:2"), (1, "RATE", "1:1"),
        (2, "WISH", "2:1"),
        (3, "CLICK", "1:1"),
    ])
    out = _top_users(df, "galaxy", n=10)
    assert [u["user_id"] for u in out] == [1, 2, 3]
    assert out[0]["events"] == 3
    assert out[0]["metric"] == "활동"


def test_galaxy_contents_is_unique_count():
    df = _df([
        (1, "CLICK", "1:1"), (1, "CLICK", "1:1"), (1, "RATE", "1:2"),
    ])
    out = _top_users(df, "galaxy")
    assert out[0]["events"] == 3
    assert out[0]["contents"] == 2  # 1:1, 1:2


# ── mars: PLAY 가 있으면 PLAY 만 카운트 ───────────────────────────────


def test_mars_prefers_play_when_present():
    df = _df([
        (1, "PLAY", "1:1"), (1, "PLAY", "1:1"),  # 2 plays
        (1, "CLICK", "1:1"),                       # ignored
        (2, "CLICK", "1:1"),                       # mars w/o PLAY → 빠짐
    ])
    out = _top_users(df, "mars")
    assert out[0]["user_id"] == 1
    assert out[0]["events"] == 2
    assert out[0]["metric"] == "PLAY"
    # user 2 는 PLAY 가 없으니 list 에 없어야 함
    assert all(u["user_id"] != 2 for u in out)


def test_mars_falls_back_to_total_when_no_play():
    df = _df([
        (1, "CLICK", "1:1"), (1, "WISH", "2:1"),
        (2, "CLICK", "1:1"),
    ])
    out = _top_users(df, "mars")
    assert out[0]["user_id"] == 1
    assert out[0]["events"] == 2
    assert out[0]["metric"] == "활동"


# ── adult: RENTAL + POSSESSION ────────────────────────────────────────


def test_adult_counts_purchases_only():
    df = _df([
        (1, "RENTAL", "10:1"), (1, "POSSESSION", "10:2"),
        (1, "CLICK", "10:3"),     # ignored
        (2, "PREVIEW", "10:1"),    # ignored
        (3, "RENTAL", "10:1"),
    ])
    out = _top_users(df, "adult")
    assert [u["user_id"] for u in out] == [1, 3]
    assert out[0]["events"] == 2
    assert out[0]["metric"] == "결제"


def test_adult_empty_when_no_purchases():
    df = _df([(1, "CLICK", "10:1"), (2, "PREVIEW", "10:1")])
    assert _top_users(df, "adult") == []


# ── edge cases ────────────────────────────────────────────────────────


def test_unknown_domain_returns_empty():
    df = _df([(1, "CLICK", "1:1")])
    assert _top_users(df, "ml_1m") == []


def test_empty_df_returns_empty():
    assert _top_users(pd.DataFrame(), "galaxy") == []


def test_respects_n_limit():
    df = _df([(i, "CLICK", "1:1") for i in range(1, 21)])
    assert len(_top_users(df, "galaxy", n=5)) == 5
