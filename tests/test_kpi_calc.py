"""Unit tests for `kpi_calc.py` — pure pandas helpers carried over from
remy-worker abtest utilities. No I/O; fixtures only.

Run:  pytest tests/  (from mocha root)
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import kpi_calc as kc

# ── fixtures ────────────────────────────────────────────────────────────


# 명확한 UTC 자정 + 12시간 기준 — boundary 걸치지 않도록 noon UTC 사용.
# DAY_A_NOON = 2023-11-15 12:00:00 UTC
# DAY_B_NOON = 2023-11-16 12:00:00 UTC
DAY_A_NOON = 1_700_049_600
DAY_B_NOON = 1_700_136_000


@pytest.fixture
def play_logs() -> pd.DataFrame:
    """3 users × 2 days, 6 raw play events.
    user 1 + 1:10 spans BOTH days so we can verify distinct
    (user, content, date) grouping.
    """
    return pd.DataFrame(
        {
            "user_id":    [1, 1, 2, 3, 1, 1],
            "content":    ["1:10", "1:10", "2:20", "1:10", "1:11", "1:10"],
            "created_at": [
                DAY_A_NOON,
                DAY_A_NOON + 500,
                DAY_A_NOON + 1000,
                DAY_B_NOON,        # 다음 날
                DAY_B_NOON + 100,
                DAY_B_NOON + 200,  # user 1 + 1:10 의 day-B 발생
            ],
            "total_view_time": [120, 60, 200, 300, 90, 45],
        }
    )


@pytest.fixture
def rating_logs() -> pd.DataFrame:
    """Duplicate rating by user 1 on same (user, content, date) should
    collapse to a single event."""
    return pd.DataFrame(
        {
            "user_id":    [1, 1, 2],
            "content":    ["1:10", "1:10", "2:20"],
            "created_at": [DAY_A_NOON, DAY_A_NOON + 500, DAY_A_NOON + 1000],
        }
    )


@pytest.fixture
def click_logs() -> pd.DataFrame:
    """3 click events from 2 users."""
    return pd.DataFrame(
        {
            "user_id":    [1, 2, 1],
            "content":    ["1:10", "2:20", "1:10"],
            "created_at": [DAY_A_NOON, DAY_A_NOON + 500, DAY_A_NOON + 1000],
        }
    )


# ── process_play_count_data ─────────────────────────────────────────────


def test_play_count_groups_by_user_content_date(play_logs):
    out = kc.process_play_count_data(play_logs)
    assert set(out.columns) == {"user_id", "content", "date", "value"}
    # user=1, content=1:10, day A — 2 events
    day_a = pd.Timestamp(DAY_A_NOON, unit="s").date()
    row = out[(out["user_id"] == 1) & (out["content"] == "1:10") &
              (out["date"] == day_a)]
    assert int(row["value"].iloc[0]) == 2


def test_play_count_distinct_days(play_logs):
    out = kc.process_play_count_data(play_logs)
    # user 1, content 1:10 — 2 distinct (user, content, date)
    u1 = out[(out["user_id"] == 1) & (out["content"] == "1:10")]
    assert len(u1) == 2


# ── process_play_time_data ──────────────────────────────────────────────


def test_play_time_sums_view_seconds(play_logs):
    df = play_logs.rename(columns={"created_at": "timestamp"})
    out = kc.process_play_time_data(df)
    day_a = pd.Timestamp(DAY_A_NOON, unit="s").date()
    row = out[(out["user_id"] == 1) & (out["content"] == "1:10") &
              (out["date"] == day_a)]
    assert int(row["value"].iloc[0]) == 180  # 120 + 60


# ── process_rating_data ─────────────────────────────────────────────────


def test_rating_collapses_duplicates(rating_logs):
    """Same (user, content, date) rated twice → 1 event."""
    out = kc.process_rating_data(rating_logs)
    u1 = out[(out["user_id"] == 1) & (out["content"] == "1:10")]
    assert len(u1) == 1
    assert int(u1["value"].iloc[0]) == 1


def test_rating_distinct_users(rating_logs):
    out = kc.process_rating_data(rating_logs)
    # user 1 (1 rating) + user 2 (1 rating) = 2 rows after dedup
    assert len(out) == 2


# ── process_click_data ──────────────────────────────────────────────────


def test_click_does_not_dedupe(click_logs):
    """Click events should double-count (unlike rate/wish)."""
    out = kc.process_click_data(click_logs)
    u1 = out[(out["user_id"] == 1) & (out["content"] == "1:10")]
    # 2 click events on same content/date — counted as 2 (not collapsed)
    assert int(u1["value"].iloc[0]) == 2


# ── _groupby helper (count vs sum behaviour) ────────────────────────────


def test_groupby_count_injects_value_one():
    df = pd.DataFrame({"k": ["a", "a", "b"]})
    out = kc._groupby(df, ["k"], agg="count")
    assert dict(zip(out["k"], out["value"], strict=False)) == {"a": 2, "b": 1}


def test_groupby_sum_requires_target_col():
    df = pd.DataFrame({"k": ["a", "a"], "n": [3, 4]})
    out = kc._groupby(df, ["k"], agg="sum", target_col="n")
    assert int(out.loc[out["k"] == "a", "value"].iloc[0]) == 7


def test_groupby_unsupported_agg_raises():
    df = pd.DataFrame({"k": ["a"]})
    with pytest.raises(ValueError):
        kc._groupby(df, ["k"], agg="max")  # no target_col
