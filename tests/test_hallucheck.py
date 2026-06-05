"""Unit tests for hallucheck — 답변 환각(데이터 미근거 수치) 검증.

archive 불필요 — 순수 로직.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import hallucheck

KPI = {
    "kpis": [
        {"label": "Total events", "value": 4_680_000},
        {"label": "active_users", "value": 158_000},
    ],
    "top_genres": [
        {"name": "Drama", "events": 1_994_000, "users": 100000},
        {"name": "Animation", "events": 521_000, "users": 50000},
    ],
    "top_contents": [{"content": "1:1", "events": 940_131, "users": 1747}],
}


def test_clean_when_numbers_match():
    # 답변이 KPI 값 그대로 사용 → 의심 없음
    txt = "총 468만 건의 이벤트, 활성 사용자 15.8만 명. Drama가 199.4만 건."
    assert hallucheck.check(txt, KPI) == []


def test_catches_fabricated_count():
    # 470만 = KPI에 없는 수 (468만과 tol 밖)
    txt = "총 555만 건의 이벤트가 발생했습니다."
    s = hallucheck.check(txt, KPI)
    assert any(x["kind"] == "count" for x in s)


def test_allows_derived_ratio():
    # Drama 점유율 = 1994000/4680000 ≈ 42.6% → 파생 허용
    txt = "Drama가 전체의 42.6%를 차지합니다."
    assert hallucheck.check(txt, KPI) == []


def test_allows_derived_multiple():
    # Drama/Animation = 1994000/521000 ≈ 3.83배 → 파생 허용
    txt = "Drama는 Animation의 3.83배입니다."
    assert hallucheck.check(txt, KPI) == []


def test_catches_fabricated_ratio():
    # 99% 점유 — 어떤 쌍으로도 안 나옴
    txt = "Drama가 전체의 99%를 독점합니다."
    s = hallucheck.check(txt, KPI)
    assert any(x["kind"] == "ratio" for x in s)


def test_small_integers_ignored():
    # 순위/연도/개수 (작은 정수) 는 noise → skip
    txt = "1위 Drama, 2위 Animation. 상위 10개 콘텐츠. 2026년 기준."
    assert hallucheck.check(txt, KPI) == []


def test_rounding_tolerance():
    # "약 467만" ≈ 4,670,000 vs 4,680,000 (0.2% < 2% tol) → 통과
    txt = "약 467만 건입니다."
    assert hallucheck.check(txt, KPI) == []


def test_empty_kpi_no_crash():
    assert hallucheck.check("아무 숫자 12345만", {}) == []


def test_dates_ignored():
    # 날짜/기간/파일명 날짜는 검증 대상 아님 (오탐 방지)
    txt = ("기간: 2026-05-01 ~ 2026-05-31 (2026년 5월). "
           "파일 20260501_20260531. 14일, 3시 기준.")
    assert hallucheck.check(txt, KPI) == []
