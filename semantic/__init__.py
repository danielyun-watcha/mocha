"""Semantic layer — 비즈니스 용어/지표를 '실행 가능한 계약'으로 노출.

- registry: Metric 계약 (kpi.summary 출력 위 annotation)
- glossary: 사용자 용어 ↔ 지표
- resolve:  용어 해석 · 지표 조회 · 프롬프트 카탈로그

LLM 은 SQL/pandas 를 생성하지 않고 metric key 를 호출 → 같은 질문 = 같은 정의 = 같은 숫자.
"""
from .glossary import GLOSSARY, Term
from .registry import BY_KEY, REGISTRY, MetricSpec, metrics_for_domain
from .resolve import (
    TermHit,
    answer_scaffold,
    describe_glossary,
    describe_metrics,
    metric_value,
    resolve_terms,
)

__all__ = [
    "MetricSpec", "REGISTRY", "BY_KEY", "metrics_for_domain",
    "Term", "GLOSSARY",
    "TermHit", "resolve_terms", "metric_value", "answer_scaffold",
    "describe_metrics", "describe_glossary",
]
