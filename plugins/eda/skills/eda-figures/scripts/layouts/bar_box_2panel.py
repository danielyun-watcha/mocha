"""bar_box_2panel — 분포 막대 + summary boxplot."""
import matplotlib.pyplot as plt

from ._common import insight_box_fig, clean_spines, accent_cycle


def render(key, value, theme, output_path, brief=None):
    """value: {"buckets": {...}, "boxplot": {q1, median, q3, ...}}"""
    if not isinstance(value, dict) or "buckets" not in value or "boxplot" not in value:
        return
    buckets = value["buckets"]
    box = value["boxplot"]

    if not isinstance(buckets, dict) or not isinstance(box, dict):
        return
    if "median" not in box:
        return

    fig, axes = plt.subplots(1, 2, figsize=(14, 6),
                              gridspec_kw={"width_ratios": [2, 1]})

    # Left: bar
    ax = axes[0]
    labels = list(buckets.keys())
    vals = list(buckets.values())
    accents = accent_cycle(theme)
    cols = [theme["neutral_mid"]] + [accents[i % 3] for i in range(len(labels) - 2)] + [theme["accent_red"]]
    cols = cols[:len(labels)] if len(labels) > 1 else [theme["accent_cool"]]
    bars = ax.bar(labels, vals, color=cols, edgecolor="black", linewidth=1.5)
    total = sum(vals)
    for bar, v in zip(bars, vals):
        if v > 0:
            pct = v / total * 100 if total else 0
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(vals) * 0.02,
                    f"{v/1000:.1f}K\n({pct:.0f}%)",
                    ha="center", fontsize=11, weight="bold")
    ax.set_xlabel(key.replace("_buckets", "").replace("_", " "), fontsize=14)
    ax.set_ylabel("건수", fontsize=14)
    ax.set_title("분포", fontsize=15, weight="bold", pad=15)
    clean_spines(ax)
    ax.grid(axis="y", alpha=0.3)

    # Right: boxplot
    ax = axes[1]
    bxp_data = [{
        "label": "summary",
        "whislo": box.get("p5", box.get("min", 0)),
        "q1": box["q1"], "med": box["median"], "q3": box["q3"],
        "whishi": box.get("p95", box.get("max", 0)),
        "fliers": [],
    }]
    bp = ax.bxp(bxp_data, patch_artist=True, widths=0.5, showfliers=False)
    for patch in bp["boxes"]:
        patch.set_facecolor(theme["accent_cool"])
        patch.set_edgecolor("black")
        patch.set_linewidth(1.5)
    for median in bp["medians"]:
        median.set_color("white")
        median.set_linewidth(2.5)

    ax.text(1.30, box["median"], f"중앙값\n{box['median']:.0f}",
            fontsize=12, weight="bold", va="center", color=theme["accent_cool"])
    ax.text(1.30, box["q3"], f"Q3 {box['q3']:.0f}",
            fontsize=10, va="center", color=theme["neutral_mid"])
    ax.text(1.30, box["q1"], f"Q1 {box['q1']:.0f}",
            fontsize=10, va="center", color=theme["neutral_mid"])
    if "max" in box:
        ax.text(1.30, box["max"], f"max {box['max']}",
                fontsize=11, weight="bold", va="center", color=theme["accent_red"])
        ax.axhline(box["max"], color=theme["accent_red"], linestyle=":", alpha=0.7)

    upper = box.get("max", box.get("p95", box["q3"])) * 1.1
    ax.set_ylim(0, upper)
    ax.set_ylabel("값", fontsize=14)
    ax.set_title("summary boxplot", fontsize=15, weight="bold", pad=15)
    clean_spines(ax)
    ax.grid(axis="y", alpha=0.3)

    plt.suptitle(f"{key.replace('_buckets', '')} — 분포 + 통계 요약",
                 fontsize=17, weight="bold", y=1.02)
    insight_box_fig(fig,
                    f"중앙값 {box['median']:.0f}, Q1-Q3 ({box['q1']:.0f}~{box['q3']:.0f}). "
                    f"분포의 균일도/cap을 확인.")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
