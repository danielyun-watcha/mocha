"""Semantic resolver — 용어 해석 · 지표 조회 · 프롬프트 카탈로그.

세 가지 진입점:
  resolve_terms(question, domain)   → 질문에서 비즈니스 용어 추출 → metric key 후보
  metric_value(key, domain, start, end, ...) → 계약대로 kpi.summary() pluck + 포맷 + 조회기준
  describe_metrics(domain) / describe_glossary(domain) → system prompt 주입용 markdown

metric_value 는 kpi.summary() 를 동기 호출한다(무거움). async 핸들러에서는
asyncio.to_thread 로 감싸 호출할 것.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import kpi as kpi_mod

from .glossary import GLOSSARY
from .registry import BY_KEY, MetricSpec, metrics_for_domain


# ── 용어 해석 ────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TermHit:
    term: str
    metric_key: str
    matched_alias: str
    definition_ko: str
    note: str
    domains: tuple[str, ...]


def resolve_terms(question: str, domain: str | None = None) -> list[TermHit]:
    """질문 문자열에서 glossary 용어를 매칭해 metric 후보를 돌려준다.

    alias 부분문자열 매칭(긴 alias 우선). domain 지정 시 그 도메인 용어만.
    같은 metric_key 는 1회로 dedup.
    """
    q = question.lower().replace(" ", "")
    hits: list[TermHit] = []
    seen: set[str] = set()
    for term in GLOSSARY:
        if domain and domain not in term.domains:
            continue
        # 긴 alias 부터 검사 → 더 구체적인 매칭 우선
        for alias in sorted(term.aliases_ko, key=len, reverse=True):
            if alias.lower().replace(" ", "") in q:
                if term.maps_to in seen:
                    break
                seen.add(term.maps_to)
                hits.append(TermHit(
                    term=term.canonical, metric_key=term.maps_to,
                    matched_alias=alias, definition_ko=term.definition_ko,
                    note=term.note, domains=term.domains,
                ))
                break
    return hits


# ── 값 포맷 ──────────────────────────────────────────────────────────────
def _fmt_value(v: Any, fmt: str) -> str:
    if v is None:
        return "—"
    try:
        if fmt == "pct":
            return f"{float(v) * 100:.2f}%"
        if fmt == "f2":
            return f"{float(v):.2f}"
        if fmt == "won":
            return f"₩{int(v):,}"
        if fmt == "star10":
            return f"{float(v):.1f}/10"
        return f"{int(v):,}"
    except (ValueError, TypeError):
        return str(v)


def _dig(d: dict, path: list[str]) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _criteria(spec: MetricSpec, domain: str, start: date, end: date,
              content_types: list[str] | None, action_types: list[str] | None) -> str:
    """조회 기준 문장 — 정의 + 기간 + 필터 (Glossary/Registry 정의 그대로 → 항상 일관)."""
    dom = kpi_mod.DOMAIN_LABEL.get(domain, domain)
    parts = [dom, f"{start.isoformat()} ~ {end.isoformat()}", spec.definition_ko]
    if content_types:
        parts.append(f"콘텐츠: {', '.join(content_types)}")
    if action_types:
        parts.append(f"액션: {', '.join(action_types)}")
    return " · ".join(parts)


# ── 지표 조회 ────────────────────────────────────────────────────────────
def metric_value(
    metric_key: str, domain: str, start: date, end: date,
    content_types: list[str] | None = None,
    action_types: list[str] | None = None,
) -> dict[str, Any]:
    """metric key 를 계약대로 해석해 값 + 조회기준 + caveat + 출처를 반환.

    scalar → value/display, table → rows(list).  미정의/도메인불일치는 error.
    """
    spec = BY_KEY.get(metric_key)
    if spec is None:
        return {"error": f"unknown metric: {metric_key}"}
    if domain not in spec.domains:
        return {"error": f"metric {metric_key} 은(는) domain '{domain}' 미지원 "
                         f"(지원: {', '.join(spec.domains)})"}

    res = kpi_mod.summary(domain, start, end, content_types=content_types,
                          action_types=action_types)

    if spec.resolve.startswith("kpi:"):
        label = spec.resolve[4:]
        item = next((k for k in res.get("kpis", []) if k["label"] == label), None)
        raw = item["value"] if item else None
        fmt = item["fmt"] if item else spec.fmt
    else:
        raw = _dig(res, spec.resolve.split("."))
        fmt = spec.fmt

    out: dict[str, Any] = {
        "metric": spec.key,
        "label": spec.label_ko,
        "domain": domain,
        "definition": spec.definition_ko,
        "formula": spec.formula,
        "조회기준": _criteria(spec, domain, start, end, content_types, action_types),
        "tier": spec.tier,
        "source": list(spec.source_keys),
        "caveats": list(spec.caveats),
        "kind": spec.kind,
    }
    if spec.kind == "table":
        out["rows"] = raw if isinstance(raw, list) else []
    else:
        out["value"] = raw
        out["display"] = _fmt_value(raw, fmt)
    return out


# ── system prompt 주입용 카탈로그 ────────────────────────────────────────
def answer_scaffold(
    question: str, domain: str, start: date, end: date, summary: dict,
    max_results: int = 2,
) -> dict[str, Any]:
    """이미 로드된 summary() 위에서 조회기준 + 확정 결과 블록을 만든다(재계산 X).

    점진적 출력용: AI 가 글을 쓰기 전에 '확정 결과'를 먼저 화면에 띄우기 위함.
    질문에서 용어를 해석해 상위 max_results 개 지표를 결과 블록으로 변환.
    """
    hits = resolve_terms(question, domain)
    results: list[dict[str, Any]] = []
    for h in hits[:max_results]:
        spec = BY_KEY.get(h.metric_key)
        if spec is None or domain not in spec.domains:
            continue
        if spec.resolve.startswith("kpi:"):
            label = spec.resolve[4:]
            item = next((k for k in summary.get("kpis", []) if k["label"] == label), None)
            raw = item["value"] if item else None
            fmt = item["fmt"] if item else spec.fmt
        else:
            raw = _dig(summary, spec.resolve.split("."))
            fmt = spec.fmt
        block: dict[str, Any] = {
            "metric": spec.key, "label": spec.label_ko, "kind": spec.kind,
            "caveats": list(spec.caveats),
        }
        if spec.kind == "table":
            rows = raw if isinstance(raw, list) else []
            if not rows:
                continue  # 빈 표는 선표시 안 함 (빈 블록/잘못된 dedup 방지)
            block["rows"] = rows[:5]
        else:
            if raw is None:
                continue  # 값 없으면 선표시 안 함
            block["value"] = raw
            block["display"] = _fmt_value(raw, fmt)
        results.append(block)
    criteria = None
    if hits:
        spec0 = BY_KEY.get(hits[0].metric_key)
        if spec0 is not None:
            criteria = _criteria(spec0, domain, start, end, None, None)
    return {"criteria": criteria, "results": results}


def describe_metrics(domain: str | None = None) -> str:
    """지표 계약 카탈로그(markdown). domain 지정 시 해당 도메인만 → 토큰 절약."""
    specs = metrics_for_domain(domain) if domain else list(BY_KEY.values())
    lines = [
        "## 지표 계약 (정의된 지표는 이 정의/식대로만 답하라 — 임의 재계산 금지)",
        "",
    ]
    for m in specs:
        cav = f"  ⚠️ {'; '.join(m.caveats)}" if m.caveats else ""
        lines.append(f"- `{m.key}` — {m.label_ko}: {m.definition_ko} (= {m.formula})"
                     f" [tier{m.tier}]{cav}")
    return "\n".join(lines) + "\n"


def describe_glossary(domain: str | None = None) -> str:
    """용어집(markdown). 사용자 표현 → 정규 지표. 모호 용어 기준 명시."""
    lines = ["## 비즈니스 용어집 (아래 용어는 매핑된 지표 정의를 따른다)", ""]
    for t in GLOSSARY:
        if domain and domain not in t.domains:
            continue
        note = f" — 주의: {t.note}" if t.note else ""
        lines.append(f"- {', '.join(t.aliases_ko[:4])} → `{t.maps_to}` "
                     f"({t.definition_ko}){note}")
    return "\n".join(lines) + "\n"


__all__ = [
    "TermHit", "resolve_terms", "metric_value", "answer_scaffold",
    "describe_metrics", "describe_glossary",
]
