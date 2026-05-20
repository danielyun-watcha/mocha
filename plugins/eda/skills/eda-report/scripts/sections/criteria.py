"""§집계 기준 — PANDA "기간/기준/해석" 3요소."""


# 도메인별 "기준 / 해석" 라인 (스킬별 metric 정의 보충)
DOMAIN_CRITERIA = {
    "graph_modeling": {
        "criterion": "train.ftr — k-core 2 이상으로 필터된 학습용 positive 인터랙션",
        "interpretation": [
            "`interactions`: (user, content, value) 1행 = 1 인터랙션 (시청 + 평점 + 클릭 합산)",
            "`value`: 행동별 가중치 (시청시간/평점 등을 정규화한 값)",
            "`sparsity`: 1 − (인터랙션 수 / (유저 수 × 콘텐츠 수))",
        ],
    },
    "rec_galaxy": {
        "criterion": "train.ftr — 시청·평점 등 행동 시퀀스 (k-core 적용)",
        "interpretation": [
            "`interactions`: 행동 1건 = 1 인터랙션",
            "`value`: 행동 가중치",
        ],
    },
    "rating_prediction": {
        "criterion": "ratings.ftr — 사용자 별점 (1~10 = ★0.5 ~ ★5)",
        "interpretation": [
            "`value`: 별점 × 2 (예: ★4.5 = 9)",
            "`avg_rating`: 콘텐츠별 평균 별점 (n_ratings ≥ 100 필터)",
        ],
    },
    "rec_adult": {
        "criterion": "adults.ftr — 성인관 구매·시청 트랜잭션",
        "interpretation": [
            "`total_spend`: CONTENT_TO_PRICE.pkl 매핑으로 환산한 누적 매출",
            "`n_repeats`: 동일 (user, content) 쌍의 재구매 횟수",
        ],
    },
    "negative": {
        "criterion": "hard_neg_edges.ftr — MEH(value=-1) + 저평점(★1~2.5) 부정 신호",
        "interpretation": [
            "`n_mehs`: 유저당 누른 싫어요 수",
            "`neg_ratio`: 부정 신호 / (부정 + positive)",
        ],
    },
}


def render(meta: dict) -> str:
    """§집계 기준 블록."""
    domain = meta.get("domain")
    period_start = meta.get("period_start", "?")
    period_end = meta.get("period_end", "?")
    n_days = meta.get("n_days")
    n_rows = meta.get("n_rows")
    data_path = meta.get("data_path", "?")
    n_days_str = f" ({n_days}일)" if n_days else ""

    criteria = DOMAIN_CRITERIA.get(domain, {})
    criterion = criteria.get("criterion", f"{meta.get('main_file', '?')} — 도메인별 정의 미등록")
    interpretation = criteria.get("interpretation", [])

    lines = [
        "## 📊 집계 기준",
        "",
        f"- **데이터 경로**: `{data_path}`",
        f"- **기간**: {period_start} ~ {period_end}{n_days_str}",
        f"- **행 수**: {n_rows:,}건" if n_rows else "- **행 수**: -",
        f"- **기준**: {criterion}",
    ]
    if interpretation:
        lines.append("- **해석**:")
        for it in interpretation:
            lines.append(f"  - {it}")
    return "\n".join(lines) + "\n"
