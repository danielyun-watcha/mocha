"""§시간·꼬리 분포 — daily_volume / lorenz / pareto_long_tail."""
from pathlib import Path

from ._common import fmt_int, fmt_pct, find_figure, find_figure_by_name, img_embed


def render(results: dict, figures_dir: Path | None = None, sections: str = "both") -> str:
    """§시간·꼬리 분포 섹션.

    sections: "both" (기본) | "time" (시간 분포만) | "tail" (꼬리 분포만)
    Q&A 모드에서 over-matching 방지용.
    """
    lines = []
    parts = []
    want_time = sections in ("both", "time")
    want_tail = sections in ("both", "tail")

    # 시간 분포 — daily_volume은 {date: count} dict
    dv = results.get("daily_volume", {})
    mv = results.get("monthly_volume", {})
    if want_time and (dv or mv):
        sub = ["### ⏱️ 시간 분포"]
        if dv and isinstance(dv, dict):
            counts = [v for v in dv.values() if isinstance(v, (int, float))]
            if counts:
                avg = sum(counts) / len(counts)
                peak_count = max(counts)
                peak_date = next((k for k, v in dv.items() if v == peak_count), None)
                sub.append(f"- 일평균 인터랙션: **{fmt_int(int(avg))}건** ({len(counts)}일 기준)")
                if peak_date:
                    sub.append(f"- 일별 피크: {peak_date} ({fmt_int(int(peak_count))}건)")
        fig = find_figure(figures_dir, "F2")
        if fig:
            sub.append("")
            sub.append(img_embed(fig, "일별 인터랙션 볼륨"))
        # peak_hours bar chart (PM/Infra 친화)
        peak_fig = find_figure_by_name(figures_dir, "peak_hours")
        if peak_fig:
            sub.append("")
            sub.append(img_embed(peak_fig, "시간대별 인터랙션 (TOP 10)"))
        parts.append("\n".join(sub))

    # 꼬리 분포 (long-tail)
    par = results.get("pareto_long_tail", {})
    lor = results.get("lorenz", {})
    if want_tail and (par or lor):
        sub = ["### 📉 꼬리 분포 (Long-tail)"]
        if par:
            top5 = par.get("top5pct")
            top1 = par.get("top1pct")
            top20 = par.get("top20pct")
            bullets = []
            if top1 is not None:
                bullets.append(f"- 상위 **1%** 콘텐츠 → 전체의 {fmt_pct(top1)}")
            if top5 is not None:
                bullets.append(f"- 상위 **5%** 콘텐츠 → 전체의 {fmt_pct(top5)}")
            if top20 is not None:
                bullets.append(f"- 상위 **20%** 콘텐츠 → 전체의 {fmt_pct(top20)}")
            sub.extend(bullets)
        # Gini 추정 (lorenz x_pct, y_pct에서)
        if lor and "x_pct" in lor and "y_pct" in lor:
            # Gini — eda-overview/tail.py 가 미리 계산 (single source of truth)
            gini = results.get("gini")
            if gini is not None:
                sub.append(f"- Gini 계수: **{gini:.3f}**")
        fig = find_figure(figures_dir, "F3")
        if fig:
            sub.append("")
            sub.append(img_embed(fig, "Lorenz 곡선"))
        parts.append("\n".join(sub))

    if not parts:
        return ""

    # 헤더는 실제 포함된 sub에 맞게
    if want_time and want_tail:
        header_title = "## 📈 시간·꼬리 분포"
    elif want_time:
        header_title = "## 📈 시간 분포"
    else:
        header_title = "## 📉 꼬리 분포"
    lines.append(header_title)
    lines.append("")
    lines.extend(parts)
    return "\n\n".join(lines) + "\n"
