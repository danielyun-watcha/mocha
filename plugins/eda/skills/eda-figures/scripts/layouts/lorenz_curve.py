"""lorenz_curve — 누적 점유율 (long-tail / Pareto)."""
import matplotlib.pyplot as plt

from ._common import insight_box_fig, clean_spines


def render(key, value, theme, output_path, brief=None):
    if not isinstance(value, dict):
        return

    # 두 형식 지원:
    # A) {"x_pct": [...], "y_pct": [...]}  ← lorenz
    # B) {"top1pct": 15.38, "top5pct": 40.5, ...}  ← pareto summary
    has_lorenz = "x_pct" in value and "y_pct" in value
    has_pareto = any(k.startswith("top") and k.endswith("pct") for k in value)

    fig, ax = plt.subplots(figsize=(11, 4.8))  # 세로 80%

    if has_lorenz:
        x = value["x_pct"]
        y = value["y_pct"]
        ax.plot(x, y, color=theme["accent_cool"], linewidth=3, label="실제 누적 점유")
        ax.fill_between(x, y, alpha=0.2, color=theme["accent_cool"])

    ax.plot([0, 100], [0, 100], color=theme["neutral_mid"],
            linestyle="--", linewidth=1.5, label="균등 분포 (이상선)")

    # Pareto key points
    key_pts = []
    for k, v in value.items():
        if k.startswith("top") and k.endswith("pct"):
            try:
                pct_x = float(k.replace("top", "").replace("pct", ""))
                key_pts.append((pct_x, v))
            except ValueError:
                pass

    for x_pt, y_pt in sorted(key_pts):
        ax.scatter([x_pt], [y_pt], color=theme["accent_red"], s=100, zorder=5)
        ax.annotate(f"top {x_pt:.0f}%\n→ {y_pt:.1f}%",
                    xy=(x_pt, y_pt), xytext=(x_pt + 6, max(y_pt - 10, 5)),
                    fontsize=11, weight="bold", color=theme["accent_red"],
                    arrowprops=dict(arrowstyle="->",
                                     color=theme["accent_red"], lw=1.5))

    ax.set_xlabel("누적 비율 (상위 순) (%)", fontsize=14)
    ax.set_ylabel("누적 점유율 (%)", fontsize=14)
    ax.set_title(f"{key} — Lorenz 곡선 (long-tail)",
                 fontsize=15, weight="bold", pad=15)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.legend(loc="lower right", fontsize=12)
    clean_spines(ax)
    ax.grid(alpha=0.3)

    if key_pts:
        top_n, top_share = sorted(key_pts)[min(2, len(key_pts) - 1)]
        insight_box_fig(fig,
                        f"균등선에서 크게 벌어진 곡선 → 강한 long-tail. "
                        f"상위 {top_n:.0f}%가 {top_share:.1f}% 차지.")
    else:
        insight_box_fig(fig, "균등선과 곡선의 차이가 long-tail 정도를 보여줌.")

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
