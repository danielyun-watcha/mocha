#!/usr/bin/env python3
"""Orchestrator inspector — analysis_results.json → findings + completeness 판단.

오케스트레이터의 "검증" 단계. JSON을 읽고 다음을 출력:
- findings: 구조화된 신호 (signal, value, threshold, severity, action_hint)
- completeness_score: 0~1, 답변 완성도
- ready_for_report: bool
- recommended_actions: 부족 시 추가 호출 안내

Usage:
    python3 inspect.py /path/to/analysis_results.json
    python3 inspect.py /path/to/analysis_results.json --json    # JSON 출력
"""
import argparse
import json
import sys
from pathlib import Path


SEVERITY_NOTE = "note"        # 단순 관찰
SEVERITY_NOTABLE = "notable"  # 인사이트 후보
SEVERITY_STRONG = "strong"    # 강한 신호 — 보고서 메인 발견


def _get_gini(results: dict) -> float | None:
    """Single source of truth — eda-overview/tail.py가 미리 계산한 gini 읽기."""
    return results.get("gini")


def _peak_hour_finding(case_studies: dict, daily_volume: dict) -> dict | None:
    """시간대 피크 분석. mars 도메인의 peak_hours_top10 활용."""
    peak = case_studies.get("peak_hours_top10")
    if not peak:
        return None
    top = peak[0]
    hour = top.get("hour")
    count = top.get("n_actions")
    # 일평균 비교
    if isinstance(daily_volume, dict):
        counts = [v for v in daily_volume.values() if isinstance(v, (int, float))]
        avg_daily = sum(counts) / len(counts) if counts else None
        if avg_daily and count:
            ratio = count / avg_daily
            return {
                "signal": "temporal_peak",
                "value": f"{hour}시 ({count:,}건)",
                "context": {
                    "peak_hour": hour, "peak_count": count,
                    "avg_daily": int(avg_daily), "ratio_vs_avg": round(ratio, 2),
                    "next_hour_count": peak[1].get("n_actions") if len(peak) > 1 else None,
                },
                "severity": SEVERITY_NOTABLE,
                "action_hint": "시간대 가중 학습 검토 — temporal feature 추가",
            }
    return None


def _bot_suspect_finding(case_studies: dict, overview: dict) -> dict | None:
    """활동량 outlier 유저 탐지. heavy_users TOP1이 p99 대비 X배."""
    hu = case_studies.get("heavy_users_top10") or case_studies.get("heavy_spenders_top10")
    if not hu:
        return None
    top_user = hu[0]
    n = top_user.get("n_rows") or top_user.get("n_purchases") or top_user.get("n_actions")
    if not n:
        return None
    avg_per_user = overview.get("avg_per_user", 0)
    if avg_per_user > 0:
        ratio = n / avg_per_user
        if ratio > 30:
            return {
                "signal": "bot_suspect",
                "value": f"user {top_user.get('user_id')} 활동 {n:,}건 (avg {avg_per_user:.0f} 대비 {ratio:.0f}배)",
                "context": {"user_id": top_user.get("user_id"), "n": n, "avg": avg_per_user, "ratio": round(ratio, 1)},
                "severity": SEVERITY_NOTABLE,
                "action_hint": "봇/공유계정 검증 — 별도 user_id 추적",
            }
    return None


def _concentration_finding(pareto: dict, gini: float | None) -> dict | None:
    """Head-heavy 집중도. Top 1% / 5% / Gini 종합."""
    if not pareto:
        return None
    top1 = pareto.get("top1pct")
    top5 = pareto.get("top5pct")
    if top1 is None or top5 is None:
        return None
    severity = SEVERITY_NOTE
    if top1 > 20 or top5 > 50 or (gini and gini > 0.75):
        severity = SEVERITY_NOTABLE
    if top1 > 30 or (gini and gini > 0.85):
        severity = SEVERITY_STRONG
    return {
        "signal": "head_heavy",
        "value": f"상위 1% → {top1:.1f}%, 상위 5% → {top5:.1f}%" + (f", Gini={gini:.3f}" if gini else ""),
        "context": {"top1pct": top1, "top5pct": top5, "gini": gini},
        "severity": severity,
        "action_hint": "popularity-debias 또는 long-tail 강화 sampler 검토",
    }


def _sparsity_finding(overview: dict) -> dict | None:
    """Sparsity 신호."""
    s = overview.get("sparsity_pct")
    if s is None:
        return None
    severity = SEVERITY_NOTE
    if s > 99.9:
        severity = SEVERITY_NOTABLE
    if s > 99.99:
        severity = SEVERITY_STRONG
    avg_per_user = overview.get("avg_per_user")
    return {
        "signal": "sparsity",
        "value": f"{s:.3f}%" + (f" (유저당 {avg_per_user:.1f}건)" if avg_per_user else ""),
        "context": {"sparsity_pct": s, "avg_per_user": avg_per_user},
        "severity": severity,
        "action_hint": "GNN/CF 모델 적합 / cold-start 핸들링 강화" if severity == SEVERITY_STRONG else None,
    }


def _high_value_finding(case_studies: dict) -> dict | None:
    """loyal_content의 avg_value 극단치 — 시즌 누적 의심."""
    loyal = case_studies.get("loyal_content_top10")
    if not loyal:
        return None
    top = loyal[0]
    avg_value = top.get("avg_value")
    if avg_value and avg_value > 3000:
        n_extreme = sum(1 for c in loyal if (c.get("avg_value") or 0) > 3000)
        return {
            "signal": "extreme_value",
            "value": f"평균 value 3000+ 콘텐츠 {n_extreme}개 (top: {top.get('content_key')} {avg_value:.0f})",
            "context": {"n_extreme": n_extreme, "top_value": avg_value, "top_content_key": top.get("content_key")},
            "severity": SEVERITY_NOTABLE,
            "action_hint": "시리즈 시즌 누적 가능 — 정규화 또는 콘텐츠 단위 분리 검토",
        }
    return None


def _value_distribution_finding(value_describe: dict, value_buckets: dict,
                                 data_quality: dict) -> dict | None:
    """value 분포 모양 — skew 강함, long-tail outlier."""
    if not value_describe:
        return None
    median = value_describe.get("median")
    mean = value_describe.get("mean")
    if not (median and mean and median > 0):
        return None
    skew = mean / median
    outlier = (data_quality or {}).get("value_outlier", {})
    p95 = outlier.get("p95")
    severity = SEVERITY_NOTE
    if skew > 2.0 or (p95 and p95 / median > 5):
        severity = SEVERITY_NOTABLE
    return {
        "signal": "value_distribution",
        "value": f"median {median:.0f} / mean {mean:.0f} (skew {skew:.2f}x)",
        "context": {
            "value_describe": value_describe,
            "buckets": value_buckets,
            "p95": p95,
        },
        "severity": severity,
        "action_hint": "log-transform 또는 quantile binning으로 정규화 시 학습 안정성 개선",
    }


def _quality_finding(data_quality: dict) -> dict | None:
    """데이터 품질 — null/중복/outlier 노트."""
    if not data_quality:
        return None
    n_dup = data_quality.get("n_duplicates", 0)
    null_pct = data_quality.get("null_pct_by_column", {})
    notes = data_quality.get("notes", [])
    has_null_issue = any(v > 1 for v in null_pct.values()) if null_pct else False
    if n_dup == 0 and not has_null_issue and not notes:
        return None
    severity = SEVERITY_NOTE
    if n_dup > 100 or has_null_issue:
        severity = SEVERITY_NOTABLE
    return {
        "signal": "quality_issue",
        "value": f"중복 {n_dup}건 · null 이슈 {has_null_issue} · notes {len(notes)}개",
        "context": {"data_quality": data_quality},
        "severity": severity,
        "action_hint": "데이터 파이프라인 점검 — 학습 직전 sanity check" if severity != SEVERITY_NOTE else None,
    }


def _completeness_finding(results: dict) -> tuple[float, list[str]]:
    """완성도 평가 — 3-axis boolean checklist + 가중 점수.

    Axes:
      1. signal_diversity: 최소 3종류의 신호 (sparsity, head_heavy, temporal_peak, ...) 발견
      2. suggestion_quality: 도메인 분석의 suggestion 2개 이상 + 빈 dict 아님
      3. case_richness: case_studies 3종 이상 (heavy_users/loyal_content/peak_hours 등)

    각 axis pass면 0.33 점, 3개 모두 pass면 1.0. 0.7 미만이면 ready_for_report = False.
    이전 평균식 (거의 항상 ready)보다 엄격.
    """
    missing = []

    # Axis 1: 분석 결과 핵심 키 존재
    overview = results.get("overview", {})
    has_overview_basics = bool(
        overview.get("n_users") and overview.get("n_contents") and overview.get("n_rows")
    )
    has_temporal = bool(results.get("daily_volume"))
    has_tail = bool(results.get("pareto_long_tail"))
    has_value = bool(results.get("value_describe"))
    signal_diversity_n = sum([has_overview_basics, has_temporal, has_tail, has_value])
    pass_diversity = signal_diversity_n >= 3
    if not pass_diversity:
        missing.append(f"signal_diversity: {signal_diversity_n}/4 < 3")

    # Axis 2: suggestion 품질
    sugs = results.get("analysis_suggestions", [])
    pass_sug = isinstance(sugs, list) and len(sugs) >= 2
    if not pass_sug:
        missing.append(f"analysis_suggestions: {len(sugs) if isinstance(sugs, list) else 0} < 2")

    # Axis 3: case_studies 다양성
    cs = results.get("case_studies", {})
    pass_cases = isinstance(cs, dict) and sum(1 for v in cs.values() if v) >= 3
    if not pass_cases:
        missing.append(f"case_studies: {sum(1 for v in cs.values() if v) if isinstance(cs, dict) else 0} < 3")

    # _meta 별도 체크 — critical
    if not results.get("_meta"):
        missing.append("_meta (critical)")

    score = round((pass_diversity + pass_sug + pass_cases) / 3, 2)
    return score, missing


def inspect_results(results: dict) -> dict:
    """JSON → findings + completeness + ready_for_report."""
    overview = results.get("overview", {})
    case_studies = results.get("case_studies", {})
    pareto = results.get("pareto_long_tail", {})
    lorenz = results.get("lorenz", {})
    daily_volume = results.get("daily_volume", {})

    gini = _get_gini(results)

    finders = [
        _sparsity_finding(overview),
        _concentration_finding(pareto, gini),
        _peak_hour_finding(case_studies, daily_volume),
        _bot_suspect_finding(case_studies, overview),
        _high_value_finding(case_studies),
        _value_distribution_finding(
            results.get("value_describe", {}),
            results.get("value_buckets_pct", {}),
            results.get("data_quality", {}),
        ),
        _quality_finding(results.get("data_quality", {})),
    ]
    findings = [f for f in finders if f is not None]
    # 강한 신호부터 정렬
    sev_order = {SEVERITY_STRONG: 0, SEVERITY_NOTABLE: 1, SEVERITY_NOTE: 2}
    findings.sort(key=lambda f: sev_order.get(f.get("severity"), 9))

    completeness, missing = _completeness_finding(results)

    # 추천 액션
    actions = []
    if completeness < 0.6:
        actions.append({
            "action": "rerun_casestudy",
            "args": "--top-n 20",
            "reason": f"completeness {completeness} 낮음 — case_studies/suggestions 보강 필요",
        })
    sugs = results.get("analysis_suggestions", [])
    if len(sugs) < 2:
        actions.append({
            "action": "rerun_casestudy",
            "args": "--top-n 30",
            "reason": f"suggestions {len(sugs)}개로 부족 — 더 많은 신호 추출 시도",
        })
    if not any(f["signal"] == "sparsity" for f in findings):
        actions.append({
            "action": "rerun_overview",
            "args": "",
            "reason": "overview에 sparsity 정보 없음 — overview 재실행 필요",
        })

    n_strong = sum(1 for f in findings if f["severity"] == SEVERITY_STRONG)
    n_notable = sum(1 for f in findings if f["severity"] == SEVERITY_NOTABLE)
    n_nontrivial = n_strong + n_notable
    # 3-axis 모두 pass (completeness == 1.0) + notable 신호 2개 이상이어야 ready
    # 또는 critical _meta가 있으면서 axis 2/3 pass (완전 분석 아니지만 보고 가능)
    ready_for_report = (
        completeness >= 1.0 and n_nontrivial >= 2
    ) or (
        completeness >= 0.67 and n_nontrivial >= 3 and not any("critical" in m for m in missing)
    )

    return {
        "findings": findings,
        "completeness_score": completeness,
        "missing": missing,
        "recommended_actions": actions,
        "ready_for_report": ready_for_report,
        "summary": {
            "n_findings": len(findings),
            "n_strong": n_strong,
            "n_notable": n_notable,
            "n_suggestions": len(sugs),
        },
    }


def _print_human(report: dict) -> None:
    print(f"📋 Completeness: {report['completeness_score']:.2f}  "
          f"({'✅ ready' if report['ready_for_report'] else '⚠ needs more'})")
    s = report["summary"]
    print(f"   Findings: {s['n_strong']} strong / {s['n_notable']} notable, "
          f"{s['n_suggestions']} suggestions")
    if report["missing"]:
        print(f"   Missing: {', '.join(report['missing'])}")
    print()
    print("🔍 Findings (severity order):")
    for f in report["findings"]:
        emoji = {"strong": "🔴", "notable": "🟡", "note": "⚪"}[f["severity"]]
        print(f"  {emoji} [{f['signal']}] {f['value']}")
        if f.get("action_hint"):
            print(f"      → {f['action_hint']}")
    if report["recommended_actions"]:
        print()
        print("🔄 Recommended actions:")
        for a in report["recommended_actions"]:
            print(f"  - {a['action']} {a.get('args', '')}: {a['reason']}")


def main():
    parser = argparse.ArgumentParser(description="Inspect analysis_results.json for orchestrator loop.")
    parser.add_argument("results_json")
    parser.add_argument("--json", action="store_true", help="JSON 출력 (default: human)")
    args = parser.parse_args()

    p = Path(args.results_json)
    if not p.exists():
        print(f"❌ Not found: {p}", file=sys.stderr)
        sys.exit(1)

    results = json.loads(p.read_text())
    report = inspect_results(results)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        _print_human(report)


if __name__ == "__main__":
    main()
