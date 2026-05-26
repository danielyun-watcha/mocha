"""bar_chart — 범주형 비교 / 구간 분포."""
import matplotlib.pyplot as plt

from ._common import insight_box_fig, clean_spines, accent_cycle


def render(key, value, theme, output_path, brief=None):
    if not isinstance(value, dict):
        return
    items = [(k, v) for k, v in value.items() if isinstance(v, (int, float))]
    if len(items) < 2:
        return

    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    is_pct = key.endswith("_pct")
    unit = "%" if is_pct else ""

    # 색: 최대값(인사이트 핵심)만 pastel red, 나머지는 pastel gray
    PASTEL_RED = "#E89B9B"   # 부드러운 빨강
    PASTEL_GRAY = "#C8CDD4"  # 부드러운 회색
    max_idx = vals.index(max(vals))
    cols = [PASTEL_RED if i == max_idx else PASTEL_GRAY for i, _ in enumerate(items)]

    fig, ax = plt.subplots(figsize=(10, 5.5), facecolor="white")
    ax.set_facecolor("white")
    bars = ax.bar(labels, vals, color=cols, edgecolor="none", linewidth=0)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(vals) * 0.015,
                f"{v:.1f}{unit}" if is_pct else f"{v:,}",
                ha="center", fontsize=10, color="#333")

    ax.set_xlabel(key.replace("_buckets", "").replace("_pct", "").replace("_", " "),
                  fontsize=12, color="#555")
    ax.set_ylabel(f"비율 ({unit})" if is_pct else "건수", fontsize=12, color="#555")
    ax.set_title(f"{key} — 구간 분포", fontsize=16, weight="bold", loc="left",
                 pad=15, color="#1a1a1a")
    clean_spines(ax)
    ax.grid(False)
    ax.tick_params(colors="#555")
    if is_pct:
        ax.set_ylim(0, max(vals) * 1.2)

    insight_box_fig(fig, f"최대 구간: {labels[max_idx]} ({vals[max_idx]:.1f}{unit})")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
