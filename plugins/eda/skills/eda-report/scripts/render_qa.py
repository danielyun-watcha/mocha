#!/usr/bin/env python3
"""eda-report Q&A 모드 — 자연어 질문 → 부분 답변 MD (PANDA 5단 구조)."""
import argparse
import json
import os
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from sections import header, criteria, overview_section, temporal_tail, insights, appendix
from sections._inspector_loader import load_inspect_results


# 질문 키워드 → 매칭될 case_study 키
QUESTION_ROUTES = [
    (r"큰손|헤비.*유저|heavy.*user|매출|spender", ["heavy_users_top10", "heavy_spenders_top10"]),
    (r"충성|다회차|loyal|repeat", ["loyal_content_top10", "repeat_buyers_top10"]),
    (r"피크|시간대|peak.*hour", ["peak_hours_top10"]),
    (r"베스트|bestseller|많이.*팔|판매", ["bestseller_content_top10"]),
    (r"별점|rating|평가.*많|active.*rater", ["active_raters_top10", "highly_rated_content_top10"]),
    (r"별점.*낮|최저.*평점|disliked", ["most_disliked_content_top10"]),
    (r"meh|싫어요|negative.*heavy", ["meh_heavy_users_top10"]),
    (r"부정.*비율|neg.*ratio", ["high_neg_ratio_content_top10"]),
    (r"저평점|low.*rating", ["low_rating_heavy_users_top10"]),
]

# 트리거를 시간과 꼬리로 분리 (over-matching 방지)
OVERVIEW_TRIGGERS = re.compile(r"개요|얼마나|몇 명|규모|sparsity|희소|interactions per")
TIME_TRIGGERS = re.compile(r"시간|일별|월별|피크|hour|peak", re.IGNORECASE)
TAIL_TRIGGERS = re.compile(r"꼬리|롱테일|long.?tail|lorenz|pareto|gini|상위|head.?heavy", re.IGNORECASE)

# case_study key → 관련된 finding signal
SIGNAL_FOR_CASESTUDY = {
    "heavy_users_top10": {"bot_suspect", "head_heavy"},
    "heavy_spenders_top10": {"bot_suspect"},
    "loyal_content_top10": {"extreme_value", "head_heavy"},
    "peak_hours_top10": {"temporal_peak"},
    "bestseller_content_top10": {"head_heavy"},
    "repeat_buyers_top10": {"repeat_pattern"},
    "active_raters_top10": {"bot_suspect"},
    "highly_rated_content_top10": {"perfect_score"},
    "most_disliked_content_top10": {"perfect_score"},
    "meh_heavy_users_top10": {"meh_concentration"},
    "low_rating_heavy_users_top10": {"meh_concentration"},
    "high_neg_ratio_content_top10": {"negative_pool"},
}


def _try_load_inspect(results: dict) -> dict | None:
    """공통 loader 호출 — _inspector_loader.py 참고."""
    return load_inspect_results(results, SKILL_DIR, strict=False)


def route_question(q: str, available_keys: list[str]) -> list[str]:
    """질문 → 매칭되는 case_study 키. 없으면 빈 리스트."""
    matched = []
    for pattern, keys in QUESTION_ROUTES:
        if re.search(pattern, q, re.IGNORECASE):
            matched.extend([k for k in keys if k in available_keys])
    seen = set()
    return [k for k in matched if not (k in seen or seen.add(k))]


def derive_relevant_signals(question: str, matched_keys: list[str]) -> set:
    """질문 + 매칭된 case_study → 관련 signal 집합. insights 필터링에 사용."""
    signals = set()
    for k in matched_keys:
        signals.update(SIGNAL_FOR_CASESTUDY.get(k, set()))
    if TIME_TRIGGERS.search(question):
        signals.add("temporal_peak")
    if TAIL_TRIGGERS.search(question):
        signals.add("head_heavy")
    if OVERVIEW_TRIGGERS.search(question):
        signals.update({"sparsity", "head_heavy"})
    return signals


def derive_temporal_mode(question: str) -> str | None:
    """질문 → temporal_tail 어떤 sub 보여줄지. "time" | "tail" | "both" | None."""
    t = bool(TIME_TRIGGERS.search(question))
    a = bool(TAIL_TRIGGERS.search(question))
    if t and a:
        return "both"
    if t:
        return "time"
    if a:
        return "tail"
    return None


def main():
    parser = argparse.ArgumentParser(description="Q&A mode — partial answer MD.")
    parser.add_argument("results_json")
    parser.add_argument("--question", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--figures-dir", default=None)
    args = parser.parse_args()

    results = json.loads(Path(args.results_json).read_text())
    meta = results.get("_meta", {})
    figures_dir = Path(args.figures_dir).resolve() if args.figures_dir else None
    inspect_report = _try_load_inspect(results)

    cs_keys = list(results.get("case_studies", {}).keys())
    matched_keys = route_question(args.question, cs_keys)
    relevant_signals = derive_relevant_signals(args.question, matched_keys)
    temporal_mode = derive_temporal_mode(args.question)

    sections_md = [header.render(meta, mode="qa", question=args.question)]

    if OVERVIEW_TRIGGERS.search(args.question):
        sections_md.append(overview_section.render(results, figures_dir))
    if temporal_mode:
        sections_md.append(temporal_tail.render(results, figures_dir, sections=temporal_mode))
    if matched_keys:
        sections_md.append(appendix.render(results, filter_keys=matched_keys).replace(
            "## 📎 Appendix — Case Studies", "## 📅 결과"
        ))

    sections_md.append(criteria.render(meta))

    sugs = results.get("analysis_suggestions", [])
    if sugs:
        # relevant_signals 비면 None으로 (필터 없이 전부) — fallback
        rs = relevant_signals if relevant_signals else None
        sections_md.append(insights.render(results, inspect_report, relevant_signals=rs))

    has_content = any(s.strip() for s in sections_md[1:-1])
    if not has_content:
        sections_md.insert(1, _fallback_no_match(args.question, cs_keys))

    doc = "\n\n".join([s for s in sections_md if s.strip()])

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(doc + "\n")
        print(f"✅ Saved: {out_path}")
        print(f"   Matched case_studies: {matched_keys or '(none — fallback)'}")
        print(f"   Relevant signals: {sorted(relevant_signals) or '(none)'}")
        print(f"   Temporal mode: {temporal_mode or '-'}")
    else:
        print(doc)


def _fallback_no_match(q: str, available_keys: list[str]) -> str:
    return (
        f"## ❓ 매칭되는 분석 없음\n\n"
        f"질문: _{q}_\n\n"
        f"현재 결과에서 사용 가능한 케이스 스터디:\n"
        + "\n".join(f"- `{k}`" for k in available_keys)
    )


if __name__ == "__main__":
    main()
