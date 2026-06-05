"""답변 환각 검증 — deterministic, LLM 호출 없음 (ms 단위).

LLM 답변(숫자·인사이트)이 inline KPI 데이터에 없는 수치를 지어냈는지 사후 체크.
스트리밍 종료 후 전체 텍스트로 1회만 호출.

전략:
1. KPI 데이터(dict)에서 모든 수치값을 "근거 집합"으로 수집 + 그들로 계산 가능한
   파생값(비율 %, 배수 ×)도 허용.
2. 답변 텍스트에서 숫자 토큰 추출 ("468만", "1,994만", "49.3%", "3.8배" 등).
3. 각 숫자가 근거 집합과 ±tolerance 안에서 매칭되는지. 안 되면 환각 의심.

오탐(false positive) 줄이는 쪽으로 보수적 — 순위(1·2·3), 작은 정수(연도/개수),
tolerance 내 근사는 통과. "데이터에 전혀 없는 큰 수"만 잡는다.
"""
from __future__ import annotations

import re

# 큰 수만 검증 (작은 정수는 순위/연도/개수 등 노이즈 → skip)
_MIN_CHECK = 1000
# 상대 오차 허용 (LLM 반올림: "1,994만"≈19,940,000, "약 20만" 등)
_REL_TOL = 0.02


def _collect_numbers(obj, out: set[float]) -> None:
    """KPI dict/list 안의 모든 int/float 수치를 재귀 수집."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect_numbers(v, out)


def _evidence_set(kpi_data: dict) -> set[float]:
    """근거 수치 집합 = KPI 원값 + 쌍별 비율(%)·배수(×).

    인사이트가 자주 쓰는 "A가 전체의 49%", "B의 3.8배" 같은 파생값을 KPI 원값
    들로부터 계산 가능하면 허용 (환각 아님)."""
    base: set[float] = set()
    _collect_numbers(kpi_data, base)
    vals = [v for v in base if v != 0]
    derived: set[float] = set()
    # 큰 값 위주로만 파생 (조합 폭발 방지 — 상위 40개)
    big = sorted({v for v in vals if abs(v) >= _MIN_CHECK}, reverse=True)[:40]
    for a in big:
        for b in big:
            if b and a != b:
                derived.add(a / b * 100)   # 점유율 %
                derived.add(a / b)         # 배수 ×
    return base | derived


_NUM_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(억|만|천|%|배|x|X)?")
_UNIT = {"억": 1e8, "만": 1e4, "천": 1e3}
# 날짜류 토큰 (검증 대상 아님): 2026 / 2026-05-01 / 20260601 / 5월 / 1일 등
_DATE_RE = re.compile(
    r"\d{4}\s*[-./년]\s*\d{1,2}\s*[-./월]?\s*\d{0,2}"     # 2026-05-01, 2026년 5월
    r"|20\d{6}"                                            # 파일명 날짜 20260601 (8자리 우선)
    r"|\b20\d{2}\b"                                        # 연도 2026
    r"|\d{1,2}\s*[월일시]"                                  # 5월, 14일, 3시
)


def _date_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _DATE_RE.finditer(text)]


def _parse_answer_numbers(text: str) -> list[tuple[float, str, str]]:
    """답변에서 (값, 원문, 단위) 리스트. 만/억/%/배 단위 해석. 날짜류 제외."""
    date_spans = _date_spans(text)

    def _in_date(pos: int, end: int) -> bool:
        return any(ds <= pos and end <= de for ds, de in date_spans)

    out = []
    for m in _NUM_RE.finditer(text):
        if _in_date(m.start(), m.end()):
            continue
        raw = m.group(0).strip()
        num_s, unit = m.group(1), m.group(2)
        try:
            v = float(num_s.replace(",", ""))
        except ValueError:
            continue
        if unit in _UNIT:
            v *= _UNIT[unit]
        out.append((v, raw, unit))
    return out


def check(answer_text: str, kpi_data: dict) -> list[dict]:
    """환각 의심 수치 목록 반환. 빈 list = 깨끗.

    각 항목: {"text": 원문, "value": 해석값, "kind": "count"|"ratio"}
    """
    if not kpi_data:
        return []
    evidence = _evidence_set(kpi_data)
    ev_sorted = sorted(evidence)
    suspects = []
    for v, raw, unit in _parse_answer_numbers(answer_text):
        is_ratio = unit in ("%", "배", "x", "X")
        # count: 작은 수는 skip (순위/연도/개수 노이즈)
        if not is_ratio and abs(v) < _MIN_CHECK:
            continue
        # 근거 집합에 ±tol 매칭 있나 (binary-search 없이 단순 — 집합 작음)
        ok = any(abs(v - e) <= max(_REL_TOL * abs(e), 0.5) for e in ev_sorted)
        if not ok:
            suspects.append({"text": raw, "value": v,
                             "kind": "ratio" if is_ratio else "count"})
    return suspects


__all__ = ["check"]
