"""Unit tests for KPI metric calculation functions.

Run:  pytest tests/  (from mocha root)
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import kpi


@pytest.fixture
def ua_sample() -> pd.DataFrame:
    """3 users × 4 actions (CLICK, PLAY, WISH, BUY) matrix."""
    return pd.DataFrame(
        {
            "user_id": [1, 2, 3],
            "CLICK": [10, 0, 5],
            "PLAY":  [3, 0, 2],
            "WISH":  [1, 1, 0],
            "BUY":   [0, 0, 1],
        }
    )


def test_per_user_average(ua_sample):
    # CLICK 합 = 15, user 3명 → 평균 5.0
    assert kpi._per_user(ua_sample, "CLICK") == pytest.approx(5.0)
    # PLAY 합 = 5, 3명 → 1.666...
    assert kpi._per_user(ua_sample, "PLAY") == pytest.approx(5 / 3)


def test_per_user_missing_action(ua_sample):
    # 존재하지 않는 action → 0
    assert kpi._per_user(ua_sample, "NONEXISTENT") == 0.0


def test_per_user_empty():
    empty = pd.DataFrame(columns=["user_id", "CLICK"])
    assert kpi._per_user(empty, "CLICK") == 0.0


def test_binary_rate(ua_sample):
    # CLICK > 0 user 2명 / 전체 3명 → 0.6666
    assert kpi._binary_rate(ua_sample, "CLICK") == pytest.approx(2 / 3)
    # BUY > 0 user 1명 → 0.333
    assert kpi._binary_rate(ua_sample, "BUY") == pytest.approx(1 / 3)
    # 아무도 안 한 action → 0
    ua = ua_sample.copy()
    ua["NEVER"] = [0, 0, 0]
    assert kpi._binary_rate(ua, "NEVER") == 0.0


def test_ratio_total(ua_sample):
    # PLAY/CLICK = 5/15 = 0.333
    assert kpi._ratio_total(ua_sample, "PLAY", "CLICK") == pytest.approx(5 / 15)
    # CLICK이 0인 user 있어도 합 기준
    # BUY/CLICK = 1/15
    assert kpi._ratio_total(ua_sample, "BUY", "CLICK") == pytest.approx(1 / 15)


def test_ratio_total_zero_denominator(ua_sample):
    ua = ua_sample.copy()
    ua["ZERO"] = [0, 0, 0]
    # _safe_div(x, 0) should return 0
    assert kpi._ratio_total(ua, "PLAY", "ZERO") == 0.0


def test_replay_rate(ua_sample):
    # CLICK ≥1 user 2명, ≥2 user 2명 (10, 5) → 2/2 = 1.0
    assert kpi._replay_rate(ua_sample, "CLICK") == pytest.approx(1.0)
    # WISH ≥1 user 2명 (1,1), ≥2 user 0명 → 0.0
    assert kpi._replay_rate(ua_sample, "WISH") == 0.0


def test_per_user_ratio_mean(ua_sample):
    # 유저별 PLAY/CLICK 평균
    # user1: 3/10 = 0.3, user2: 0/0 → 0 (fillna), user3: 2/5 = 0.4
    # 평균 = (0.3 + 0 + 0.4) / 3 = 0.2333
    assert kpi._per_user_ratio_mean(ua_sample, "PLAY", "CLICK") == pytest.approx(
        (0.3 + 0 + 0.4) / 3
    )


def test_ucpu():
    # 유저별 unique content count
    df = pd.DataFrame(
        {
            "user_id": [1, 1, 1, 2, 2, 3],
            "content": ["A", "B", "A", "C", "D", "E"],  # u1:{A,B}=2, u2:{C,D}=2, u3:{E}=1
        }
    )
    # avg = (2 + 2 + 1) / 3 = 1.666
    assert kpi._ucpu(df, pd.DataFrame()) == pytest.approx(5 / 3)


def test_ucpu_empty():
    assert kpi._ucpu(pd.DataFrame(), pd.DataFrame()) == 0.0


def test_top_contents_basic():
    df = pd.DataFrame(
        {
            "user_id":     [1, 2, 3, 1, 2, 4, 5],
            "content":     ["A", "A", "A", "B", "B", "C", "C"],
            "action_type": ["RATE"] * 7,
        }
    )
    out = kpi._top_contents(df, n=2)
    # 가장 많은 events 인 A: 3 events, 3 users
    assert out[0]["content"] == "A"
    assert out[0]["events"] == 3
    assert out[0]["users"] == 3
    # next: B (2 events, 2 users) — tie with C in events 2 but ordering depends
    assert out[1]["events"] == 2
