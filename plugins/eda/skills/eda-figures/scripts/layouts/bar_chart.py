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

    fig, ax = plt.subplots(figsize=(12, 4.8))  # 세로 80%
    bars = ax.bar(labels, vals, color=cols, edgecolor="black", linewidth=1.5)
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(vals) * 0.02,
                f"{v:.1f}{unit}" if is_pct else f"{v:,}",
                ha="center", fontsize=13, weight="bold")

    ax.set_xlabel(key.replace("_buckets", "").replace("_pct", "").replace("_", " "),
                  fontsize=14)
    ax.set_ylabel(f"비율 ({unit})" if is_pct else "건수", fontsize=14)
    ax.set_title(f"{key} — 구간 분포", fontsize=15, weight="bold", pad=15)
    clean_spines(ax)
    ax.grid(axis="y", alpha=0.3)
    if is_pct:
        ax.set_ylim(0, max(vals) * 1.2)

    insight_box_fig(fig, f"최대 구간: {labels[max_idx]} ({vals[max_idx]:.1f}{unit})")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
