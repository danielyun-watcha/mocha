"""venn_overlap — 2~3개 집합 겹침."""
import matplotlib.pyplot as plt

from ._common import insight_box_fig, accent_cycle


def render(key, value, theme, output_path, brief=None):
    """value: 2-set 또는 3-set Venn 데이터.
    형식 A (3-set): {"a_only", "b_only", "c_only", "ab", "ac", "bc", "abc"}
    형식 B (2-set): {"a_only", "b_only", "intersection"}
    """
    if not isinstance(value, dict):
        return
    try:
        from matplotlib_venn import venn2, venn3
    except ImportError:
        print("  matplotlib_venn not installed; skipping venn_overlap")
        return

    accents = accent_cycle(theme)
    fig, ax = plt.subplots(figsize=(10, 7))

    # 3-set 시도
    keys = list(value.keys())
    if len(keys) >= 7:  # 3-set Venn
        subsets = (
            value.get("a_only", 0), value.get("b_only", 0), value.get("ab", 0),
            value.get("c_only", 0), value.get("ac", 0), value.get("bc", 0),
            value.get("abc", 0),
        )
        v = venn3(subsets=subsets,
                  set_labels=value.get("labels", ("A", "B", "C")),
                  set_colors=accents,
                  alpha=0.55, ax=ax)
    else:  # 2-set
        a = value.get("a_only", 0)
        b = value.get("b_only", 0)
        ab = value.get("intersection", value.get("ab", 0))
        v = venn2(subsets=(a, b, ab),
                  set_labels=value.get("labels", ("A", "B")),
                  set_colors=accents[:2],
                  alpha=0.55, ax=ax)

    ax.set_title(f"{key} — 집합 겹침 (Venn)",
                 fontsize=15, weight="bold", pad=15)
    insight_box_fig(fig, "겹치는 영역 크기 = 두 집합 모두에 속한 원소 수.")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
