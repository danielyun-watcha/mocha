"""pie_chart — 2~5 카테고리 비율."""
import matplotlib.pyplot as plt

from ._common import insight_box_fig, accent_cycle


def render(key, value, theme, output_path, brief=None):
    # value: {"label_pct": pct, "label_n": n, ...} 또는 {"label": pct}
    if not isinstance(value, dict):
        return
    items = []
    for k, v in value.items():
        if k.endswith("_pct") and isinstance(v, (int, float)):
            label = k.replace("_pct", "").replace("_", " ")
            items.append((label, v))
        elif isinstance(v, (int, float)) and not k.endswith("_n"):
            items.append((k, v))
    if len(items) < 2 or len(items) > 5:
        return

    labels = [k for k, _ in items]
    sizes = [v for _, v in items]
    cols = accent_cycle(theme)[:len(items)] + [theme["neutral_mid"], theme["accent_red"]]
    cols = cols[:len(items)]

    fig, ax = plt.subplots(figsize=(9, 7))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=labels, colors=cols, autopct="%1.1f%%", startangle=90,
        wedgeprops={"edgecolor": "white", "linewidth": 2},
        textprops={"fontsize": 14, "weight": "bold"},
    )
    for at in autotexts:
        at.set_color("white")
        at.set_fontsize(16)
        at.set_weight("bold")

    ax.set_title(f"{key} — 카테고리 비율",
                 fontsize=15, weight="bold", pad=15)

    top_label, top_pct = max(items, key=lambda x: x[1])
    insight_box_fig(fig, f"가장 큰 카테고리: {top_label} ({top_pct:.1f}%)")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
