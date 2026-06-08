"""TDD: start > end (역전 윈도우) 검증.

거꾸로 된 날짜는 조용한 빈 결과(오답)가 아니라 명시적 ValueError 로 막는다.
archive 불필요 — 검증은 데이터 읽기 전에 발생.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import kpi


def test_validate_window_helper_ok():
    # 정상/동일 날짜는 통과 (예외 없음)
    kpi._validate_window(date(2026, 5, 1), date(2026, 5, 31))
    kpi._validate_window(date(2026, 5, 1), date(2026, 5, 1))  # 같은 날 허용


def test_validate_window_helper_reversed():
    with pytest.raises(ValueError):
        kpi._validate_window(date(2026, 5, 31), date(2026, 5, 1))


def test_top_items_reversed_raises():
    with pytest.raises(ValueError):
        kpi.top_items("mars", "PLAY", date(2026, 5, 31), date(2026, 5, 1))


def test_summary_fast_reversed_raises():
    with pytest.raises(ValueError):
        kpi.summary_fast("mars", date(2026, 5, 31), date(2026, 5, 1))


def test_summary_reversed_raises():
    with pytest.raises(ValueError):
        kpi.summary("mars", date(2026, 5, 31), date(2026, 5, 1))
