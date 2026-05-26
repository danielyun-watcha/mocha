"""boxplot — 2개+ 그룹의 분포(quartile) 비교. 범위가 크면 log scale."""
import matplotlib.pyplot as plt

from ._common import insight_box_fig, clean_spines, accent_cycle


def render(key, value, theme, output_path, brief=None):
    if not isinstance(value, dict):
        return
    # value: {"group_a": {"q1":..,"median":..,"q3":..,"p5":..,"p95":..}, ...}
    groups = [(k, v) for k, v in value.items() if isinstance(v, dict) and "median" in v]
    if len(groups) < 1:
        return

    bxp_data = []
    for label, stats in groups:
        bxp_data.append({
            "label": label,
            "whislo": stats.get("p5", stats.get("min", 0)),
            "q1": stats["q1"],
            "med": stats["median"],
            "q3": stats["q3"],
            "whishi": stats.get("p95", stats.get("max", 0)),
            "fliers": [],
        })

    accents = accent_cycle(theme)
    cols = [accents[i % len(accents)] for i in range(len(groups))]

    fig, ax = plt.subplots(figsize=(11, 6))
    bp = ax.bxp(bxp_data, patch_artist=True, widths=0.5, showfliers=False)
    for patch, c in zip(bp["boxes"], cols):
        patch.set_facecolor(c)
        patch.set_edgecolor("black")
        patch.set_linewidth(1.5)
    for median in bp["medians"]:
        median.set_color("white")
        median.set_linewidth(2.5)

    # Median annotation
    for i, (label, stats) in enumerate(groups):
        ax.text(i + 1 + 0.30, stats["median"],
                f"중앙값\n{stats['median']:.0f}",
                fontsize=12, weight="bold", va="center", color=cols[i])

    # 범위가 100배+ 차이면 log scale
    medians = [s["median"] for _, s in groups]
    max_p95 = max(s.get("p95", s.get("max", 0)) for _, s in groups)
    min_p5 = max(min(s.get("p5", s.get("min", 1)) for _, s in groups), 1)
    if max_p95 / max(min_p5, 1) > 100:
        ax.set_yscale("log")
        scale_note = " (log scale)"
    else:
        scale_note = ""

    ax.set_ylabel(f"value{scale_note}", fontsize=14)
    ax.set_title(f"{key} — 분포 비교 (boxplot)",
                 fontsize=15, weight="bold", pad=15)
    clean_spines(ax)
    ax.grid(axis="y", alpha=0.3, which="both")

    if len(groups) == 2:
        ratio = medians[1] / max(medians[0], 1)
        insight_box_fig(fig,
                        f"{groups[1][0]} 중앙값이 {groups[0][0]}의 {ratio:.1f}배"
                        if ratio > 1 else
                        f"{groups[0][0]} 중앙값이 {groups[1][0]}의 {1/ratio:.1f}배")
    else:
        insight_box_fig(fig, "그룹별 분포 비교 — 박스 크기로 IQR, 가운데 선이 중앙값.")

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
