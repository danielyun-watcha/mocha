"""§분포 분석 — 그림 먼저, 그림 밑에 짧은 인사이트 설명.

원칙:
- 그림과 같은 정보를 표로 다시 보여주지 않음
- 그림 아래 1-2줄 데이터 기반 설명만
- 단순 숫자 나열 X — 의미 있는 비교/패턴만
"""
from pathlib import Path

from ._common import fmt_int, fmt_pct, find_figure_by_name, img_embed


def _temporal_block(results: dict, figures_dir: Path | None) -> str:
    dv = results.get("daily_volume", {})
    if not dv or not isinstance(dv, dict):
        return ""
    counts = [v for v in dv.values() if isinstance(v, (int, float))]
    if not counts:
        return ""
    avg = sum(counts) / len(counts)
    peak_count = max(counts)
    peak_date = next((k for k, v in dv.items() if v == peak_count), None)
    min_count = min(counts)
    min_date = next((k for k, v in dv.items() if v == min_count), None)
    n_days = len(counts)
    fluctuation = peak_count / min_count if min_count > 0 else 0

    # 추세 — 첫 7일 평균 vs 마지막 7일 평균
    items = sorted(dv.items())  # date 정렬
    first_week = [v for _, v in items[:min(7, n_days)]]
    last_week = [v for _, v in items[max(0, n_days - 7):]]
    first_avg = sum(first_week) / len(first_week) if first_week else 0
    last_avg = sum(last_week) / len(last_week) if last_week else 0
    trend_pct = (last_avg - first_avg) / first_avg * 100 if first_avg > 0 else 0

    fig = find_figure_by_name(figures_dir, "daily_volume")
    lines = ["### ⏱️ 시간 분포", ""]
    if fig:
        lines.append(img_embed(fig, "일별 인터랙션 추이"))
        lines.append("")
    # 간결 1줄 결론만 (깊이 해석은 § 도메인 깊이 해석 섹션에서)
    trend_text = ""
    if abs(trend_pct) > 10:
        direction = "급증" if trend_pct > 30 else ("증가" if trend_pct > 0 else "감소")
        trend_text = f", 마지막 주 시작 주 대비 **{trend_pct:+.0f}%** {direction}"
    lines.append(
        f"> 일평균 **{fmt_int(int(avg))}건** · 변동 **{fluctuation:.2f}배** "
        f"({min_date} {fmt_int(int(min_count))} ~ {peak_date} {fmt_int(int(peak_count))}){trend_text}"
    )
    lines.append("")
    return "\n".join(lines)


def _long_tail_block(results: dict, figures_dir: Path | None) -> str:
    par = results.get("pareto_long_tail", {})
    if not par:
        return ""
    top1 = par.get("top1pct")
    top5 = par.get("top5pct")
    top20 = par.get("top20pct")
    # Gini — eda-overview/tail.py가 미리 계산 (single source of truth)
    gini = results.get("gini")

    fig = find_figure_by_name(figures_dir, "pareto")
    lines = ["### 📉 콘텐츠 인기 (Long-tail)", ""]
    if fig:
        lines.append(img_embed(fig, "Top X% 콘텐츠의 상호작용 점유율"))
        lines.append("")
    # 간결 1줄 결론 (깊이 해석은 § 도메인 깊이 해석에서)
    n_contents = results.get("overview", {}).get("n_contents")
    parts = []
    if top5 is not None and top20 is not None:
        pareto_match = "준수" if 70 <= top20 <= 85 else ("초강성" if top20 > 85 else "약함")
        gini_part = f" · Gini **{gini:.3f}**" if gini else ""
        parts.append(
            f"상위 **5%** → 전체의 **{top5:.1f}%** · "
            f"상위 **20%** → **{top20:.1f}%** (Pareto 80-20 {pareto_match}){gini_part}"
        )
    if top1 is not None and n_contents:
        n_top1 = int(n_contents * 0.01)
        parts.append(f"콘텐츠 약 **{n_top1}개**가 시청의 약 **1/{int(100/top1) if top1>0 else 0}** 차지")
    if parts:
        lines.append("> " + " · ".join(parts))
        lines.append("")
    return "\n".join(lines)


def _peak_hours_block(results: dict, figures_dir: Path | None) -> str:
    cs = results.get("case_studies", {})
    peak = cs.get("peak_hours_top10")
    if not peak:
        return ""
    top_hour = peak[0]["hour"]
    top_count = peak[0]["n_actions"]
    second_hour = peak[1]["hour"] if len(peak) > 1 else None
    second_count = peak[1]["n_actions"] if len(peak) > 1 else 0
    # Top 5 시간대가 점심대(11-15)인지 저녁대(18-22)인지
    top5_hours = [int(p["hour"]) for p in peak[:5]]
    lunch_n = sum(1 for h in top5_hours if 11 <= h <= 15)
    evening_n = sum(1 for h in top5_hours if 18 <= h <= 22)
    night_n = sum(1 for h in top5_hours if 0 <= h <= 5)
    # 전체 인터랙션 대비 top hour 점유율
    total = results.get("overview", {}).get("n_rows", 0)
    top_pct = top_count / total * 100 if total else 0

    fig = find_figure_by_name(figures_dir, "peak_hours")
    lines = ["### 🕐 시간대 분포", ""]
    if fig:
        lines.append(img_embed(fig, "시간대별 인터랙션 (TOP 10)"))
        lines.append("")
    # 간결 1줄 결론
    parts = [f"피크 **{top_hour}시** ({fmt_int(top_count)}건, 전체 **{top_pct:.1f}%**)"]
    if lunch_n >= 3:
        parts.append(f"Top 5 시간대 **{lunch_n}/5가 점심대(11-15시)**")
    elif evening_n >= 3:
        parts.append(f"Top 5 시간대 **{evening_n}/5가 저녁대(18-22시)**")
    elif night_n >= 3:
        parts.append(f"Top 5 시간대 **{night_n}/5가 심야(0-5시)**")
    lines.append("> " + " · ".join(parts))
    lines.append("")
    return "\n".join(lines)


def _value_block(results: dict, figures_dir: Path | None) -> str:
    vd = results.get("value_describe", {})
    buckets = results.get("value_buckets_pct", {})
    if not vd and not buckets:
        return ""
    fig = find_figure_by_name(figures_dir, "value_buckets")
    lines = ["### 📊 Value 분포", ""]
    if fig:
        lines.append(img_embed(fig, "Value 구간 분포"))
        lines.append("")
    # 간결 1줄 결론
    parts = []
    if buckets:
        top_bucket = max(buckets.items(), key=lambda x: x[1])
        parts.append(f"가장 흔한 구간 **{top_bucket[0]}** ({top_bucket[1]:.1f}%)")
    if vd:
        median = vd.get("median")
        mean = vd.get("mean")
        max_v = vd.get("max")
        if median and mean and median > 0:
            skew = mean / median
            parts.append(f"중앙값 {median:.0f} / 평균 {mean:.0f} (skew **{skew:.2f}×**)")
        if max_v and median and max_v / median > 100:
            parts.append(f"max {max_v:.0f} = 중앙값 **{max_v/median:.0f}배** (극단치)")
    if parts:
        lines.append("> " + " · ".join(parts))
        lines.append("")
    return "\n".join(lines)


def render(results: dict, figures_dir: Path | None = None) -> str:
    parts = [
        _temporal_block(results, figures_dir),
        _long_tail_block(results, figures_dir),
        _peak_hours_block(results, figures_dir),
        _value_block(results, figures_dir),
    ]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return "\n".join(parts)
