"""stat_callout — 큰 숫자 callout 모음."""
import matplotlib.pyplot as plt

from ._common import accent_cycle


def _fmt_big(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K".rstrip("0").rstrip(".") if n < 100_000 else f"{n/1_000:.0f}K"
    if n == int(n):
        return f"{int(n):,}"
    return f"{n:.2f}"


# Key 별 사람이 읽는 라벨 (있으면 사용)
LABELS = {
    "n_rows": "시청 행수", "n_users": "유저", "n_contents": "콘텐츠",
    "n_persons": "인물", "n_tags": "태그",
    "rows_per_user_mean": "유저당 평균", "span_days": "기간(일)",
    "n_kg_edges": "KG 엣지", "n_tag_edges": "태그 엣지", "n_credit_edges": "인물 엣지",
    "date_range": "기간",
    "n_total_contents_in_pool": "콘텐츠 풀 크기",
}

# Big number 우선순위 — overview에 어떤 키가 있든 이 순서대로 4개 선택
BIG_NUMBER_PRIORITY = [
    "n_users", "n_contents", "n_rows", "rows_per_user_mean",
    "n_persons", "n_tags", "span_days",
]

# 메타 정보 — figure에 표시 안 함 (file paths, identifiers 등)
META_KEYS_SKIP = {"domain", "main_file", "data_path"}

# 부제 우선순위 — 부제에 표시할 key (list/string 값)
SUBTITLE_PRIORITY = ["date_range", "span_days"]


def render(key, value, theme, output_path, brief=None):
    if not isinstance(value, dict):
        return

    # 메타 키 제외 (domain, main_file 등 figure에 표시 안 함)
    filtered = {k: v for k, v in value.items() if k not in META_KEYS_SKIP}

    big_pool = {k: v for k, v in filtered.items() if isinstance(v, (int, float))}
    sub_pool = {}  # 부제 후보 (list/string)
    for k, v in filtered.items():
        if isinstance(v, list) and len(v) == 2:
            sub_pool[k] = f"{v[0]} ~ {v[1]}"
        elif not isinstance(v, (int, float)):
            sub_pool[k] = str(v)

    # Big number — 우선순위대로 4개 선택
    big_items = []
    for k in BIG_NUMBER_PRIORITY:
        if k in big_pool and len(big_items) < 4:
            big_items.append((k, big_pool.pop(k)))
    for k, v in big_pool.items():
        if len(big_items) >= 4:
            break
        big_items.append((k, v))

    # 부제 — SUBTITLE_PRIORITY 우선
    sub_items = []
    for k in SUBTITLE_PRIORITY:
        if k in sub_pool:
            sub_items.append((k, sub_pool.pop(k)))
        elif k in big_pool:  # span_days처럼 numeric이지만 부제로
            pass

    # sparsity_pct는 인사이트 박스로 (별도)
    sparsity = value.get("sparsity_pct")
    density = value.get("density_pct")

    fig, ax = plt.subplots(figsize=(14, 6))
    ax.axis("off")
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)

    title = brief.get("goal", "") if brief else ""
    ax.text(50, 55, title or "데이터 개요",
            ha="center", fontsize=22, weight="bold", color=theme["dark"])

    # 부제 (기간 등) — 한국어 라벨로 변환
    sub_parts = []
    for k, v in sub_items[:2]:
        label = LABELS.get(k, k.replace("_", " "))
        sub_parts.append(f"{label}: {v}")
    sub_text = " · ".join(sub_parts)
    if sub_text:
        ax.text(50, 49, sub_text, ha="center",
                fontsize=14, color=theme["neutral_mid"])

    cols = [theme["accent_cool"], theme["accent_warm"],
            theme["accent_natural"], theme["accent_red"]]
    positions = [15, 40, 65, 90]
    for (k, v), x, col in zip(big_items, positions, cols):
        ax.text(x, 30, _fmt_big(v), ha="center", va="center",
                fontsize=46, weight="bold", color=col)
        ax.text(x, 18, LABELS.get(k, k), ha="center",
                fontsize=13, color=theme["dark"])

    # 인사이트 박스 — sparsity 또는 brief의 domain_notes
    insight_text = None
    if sparsity is not None:
        if sparsity > 99:
            insight_text = f"Sparsity {sparsity:.2f}% (밀도 {density:.4f}%) — 매우 sparse한 데이터, cold-start 도전적"
        elif sparsity > 95:
            insight_text = f"Sparsity {sparsity:.2f}% (밀도 {density:.3f}%) — RecSys 일반적 범위, 학습 가능"
        else:
            insight_text = f"Sparsity {sparsity:.2f}% — 밀도 높음, 데이터 풍부"
    if brief and brief.get("domain_notes"):
        insight_text = (insight_text + " · " if insight_text else "") + brief["domain_notes"]
    if insight_text:
        ax.text(50, 7, insight_text,
                ha="center", fontsize=12, weight="bold",
                bbox=dict(boxstyle="round,pad=0.7", facecolor="#fff3e0",
                          edgecolor="#f57c00", linewidth=2))

    plt.savefig(output_path)
    plt.close()
