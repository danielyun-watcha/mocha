"""§헤더 — 도메인 + 분석 일시 + 데이터 한 줄."""
from ._common import fmt_compact


DOMAIN_LABEL = {
    "graph_modeling": "Mars (graph_modeling)",
    "next_watch": "Mars (next_watch)",
    "next_purchase": "Mars (next_purchase)",
    "user_bert": "Mars (user_bert)",
    "rec_galaxy": "Galaxy (rec_galaxy)",
    "rating_prediction": "Galaxy (rating_prediction)",
    "rec_adult": "성인관 (rec_adult)",
    "user_bert_adult": "성인관 (user_bert_adult)",
    "adult_foundation": "성인관 (adult_foundation)",
}


def render(meta: dict, mode: str = "full", question: str | None = None) -> str:
    """헤더 블록 — 모드별 제목 차이."""
    domain = meta.get("domain", "unknown")
    label = DOMAIN_LABEL.get(domain, domain)
    main_file = meta.get("main_file", "?")
    n_rows = fmt_compact(meta.get("n_rows"))
    generated_at = meta.get("generated_at", "")
    date_part = generated_at[:10] if generated_at else ""

    key_metric_label = meta.get("key_metric_label") or meta.get("key_metric")
    goal = meta.get("analysis_goal")

    if mode == "qa":
        title = f"# 🐼 {question or 'EDA Q&A'}"
        subtitle = f"_{label} · {main_file} ({n_rows} rows) · {date_part}_"
    else:
        title = f"# 📊 {label} EDA 리포트"
        subtitle_parts = [f"{main_file}", f"{n_rows} rows", f"분석 일시: {date_part}"]
        if key_metric_label:
            subtitle_parts.append(f"**Key metric: {key_metric_label}**")
        subtitle = "_" + " · ".join(subtitle_parts) + "_"

    out = f"{title}\n\n{subtitle}\n"
    if mode == "full" and goal:
        out += f"\n> 🎯 **분석 목적**: {goal}\n"
    return out
