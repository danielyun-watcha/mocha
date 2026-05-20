"""line_chart — 시계열 (daily/monthly volume)."""
import matplotlib.pyplot as plt
import numpy as np

from ._common import insight_box_fig, clean_spines


def render(key, value, theme, output_path, brief=None):
    if not isinstance(value, dict) or len(value) < 2:
        return
    dates = sorted(value.keys())
    vals_raw = [float(value[d]) for d in dates]
    # 단위 자동 (K 단위가 적절하면)
    use_k = max(vals_raw) > 10_000
    vals = [v / 1000 for v in vals_raw] if use_k else vals_raw
    unit = "천 건" if use_k else "건"

    x = np.arange(len(dates))

    fig, ax = plt.subplots(figsize=(13, 4.8))  # 세로 80%
    ax.plot(x, vals, color=theme["accent_cool"], linewidth=2, alpha=0.8,
            label="일별" if "daily" in key else "월별")
    ax.fill_between(x, vals, alpha=0.2, color=theme["accent_cool"])

    # 7일 이동평균 (data point ≥ 14일이면)
    window = 7
    if len(vals) >= window * 2:
        ma = np.convolve(vals, np.ones(window) / window, mode="valid")
        offset = window // 2
        ma_x = x[offset:offset + len(ma)]
        ax.plot(ma_x, ma, color=theme["accent_red"], linewidth=3,
                label=f"{window}일 이동평균")

    # tick: 매월 1일 / 또는 균등 분포
    if len(dates) > 20:
        month_starts = [i for i, d in enumerate(dates) if d.endswith("-01")]
        if month_starts:
            ax.set_xticks(month_starts)
            ax.set_xticklabels([dates[i][:7] for i in month_starts], rotation=0)
        else:
            n_ticks = min(8, len(dates))
            tick_idx = np.linspace(0, len(dates) - 1, n_ticks).astype(int)
            ax.set_xticks(tick_idx)
            ax.set_xticklabels([dates[i] for i in tick_idx], rotation=30)
    else:
        ax.set_xticks(x)
        ax.set_xticklabels(dates, rotation=30)

    ax.set_xlabel("날짜", fontsize=14)
    ax.set_ylabel(f"시청 행수 ({unit})", fontsize=14)
    ax.set_title(f"{key} — 시계열",
                 fontsize=15, weight="bold", pad=15)
    ax.legend(loc="best", fontsize=12)
    clean_spines(ax)
    ax.grid(alpha=0.3)

    start_avg = np.mean(vals[: max(1, len(vals) // 5)])
    end_avg = np.mean(vals[-max(1, len(vals) // 5):])
    pct = (end_avg / max(start_avg, 0.01) - 1) * 100
    insight_box_fig(fig,
                    f"초반 평균 {start_avg:.1f}{unit} → 후반 평균 {end_avg:.1f}{unit} "
                    f"({pct:+.0f}%)")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
