"""people_grid — 100명/100개 인포그래픽."""
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from ._common import insight_box_fig, accent_cycle


def render(key, value, theme, output_path, brief=None):
    """value: {"label": count, ...} (합 = 100)."""
    if not isinstance(value, dict):
        return
    items = [(k, int(v)) for k, v in value.items() if isinstance(v, (int, float))]
    total = sum(c for _, c in items)
    if total != 100:
        # normalize
        items = [(k, int(round(c / total * 100))) for k, c in items]

    accents = accent_cycle(theme) + [theme["accent_red"], theme["neutral_mid"]]

    fig, ax = plt.subplots(figsize=(13, 7))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 70)
    ax.axis("off")

    # 100 grid
    flat = []
    for (label, n), col in zip(items, accents):
        flat.extend([col] * n)

    idx = 0
    for row in range(10):
        i = 9 - row
        for j in range(10):
            if idx >= 100:
                break
            x = 4 + j * 4.4
            y = 18 + i * 3.5
            ax.add_patch(Rectangle((x, y), 4.0, 3.0,
                                    facecolor=flat[idx],
                                    edgecolor="white", linewidth=1.2))
            idx += 1

    ax.text(50, 66, f"{key} — 100명/100개로 보기",
            ha="center", fontsize=17, weight="bold", color=theme["dark"])

    # 2x2 Legend (max 4 categories)
    for i, ((label, n), col) in enumerate(zip(items[:4], accents[:4])):
        col_pos = i % 2
        row_pos = i // 2
        x = 8 + col_pos * 44
        y = 12 - row_pos * 4
        ax.add_patch(Rectangle((x, y), 3.5, 3.0, facecolor=col, edgecolor="black"))
        ax.text(x + 4.5, y + 1.5, f"{n}", fontsize=12, weight="bold",
                verticalalignment="center")
        ax.text(x + 9, y + 1.5, label, fontsize=11, verticalalignment="center")

    top_label, top_n = max(items, key=lambda x: x[1])
    insight_box_fig(fig, f"가장 큰 그룹: {top_label} ({top_n}명/100명)")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
