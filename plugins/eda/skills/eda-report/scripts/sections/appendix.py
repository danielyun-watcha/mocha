"""§Appendix — case_studies → MD 표."""
from ._common import fmt_int, fmt_pct, md_table


def _safe_md(value) -> str:
    """MD/HTML marker escape — prompt injection 방지 (특히 <!-- --> 시퀀스)."""
    if value is None:
        return "-"
    s = str(value)
    # HTML 주석 marker, MD 특수 토큰 escape
    s = s.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    s = s.replace("|", "\\|")  # MD table 컬럼 구분자 충돌
    return s


# case_study key → (제목, 컬럼명 매핑)
CASE_TITLES = {
    "heavy_users_top10": ("시청량 TOP10 유저 (Heavy Users)", ["순위", "user_id", "행수", "value 누적"]),
    "loyal_content_top10": ("다회차 시청 TOP10 콘텐츠 (Loyal Content)", ["순위", "content_key", "평균 value", "시청자 수"]),
    "peak_hours_top10": ("시청 피크 시간대 TOP10", ["순위", "시간대", "건수"]),
    "heavy_spenders_top10": ("매출 TOP10 큰손 유저", ["순위", "user_id", "총 매출", "구매 수"]),
    "repeat_buyers_top10": ("재구매 TOP10 (user, content) 쌍", ["순위", "user_id", "content_key", "재구매 수"]),
    "bestseller_content_top10": ("베스트셀러 TOP10 콘텐츠", ["순위", "content_key", "구매 수"]),
    "active_raters_top10": ("Rating 최다 유저 TOP10", ["순위", "user_id", "평가 수", "평균 별점"]),
    "highly_rated_content_top10": ("평균 별점 TOP10 콘텐츠 (100명+)", ["순위", "content_key", "평균 별점", "평가 수"]),
    "most_disliked_content_top10": ("최저 평점 최다 TOP10 콘텐츠", ["순위", "content_key", "최저 평점 수"]),
    "meh_heavy_users_top10": ("MEH(싫어요) 헤비 TOP10 유저", ["순위", "user_id", "MEH 수"]),
    "low_rating_heavy_users_top10": ("저평점(★2.5 이하) 헤비 TOP10 유저", ["순위", "user_id", "저평점 수"]),
    "high_neg_ratio_content_top10": ("부정 비율 TOP10 콘텐츠", ["순위", "content_key", "부정 비율", "부정/positive"]),
}

# case_study key → row 추출 함수 (값들을 헤더 순서대로 list로 반환)
def _extract_row(key: str, idx: int, item: dict) -> list:
    rank = idx + 1
    if key == "heavy_users_top10":
        return [rank, item.get("user_id"), fmt_int(item.get("n_rows")), fmt_int(item.get("value_sum"))]
    if key == "loyal_content_top10":
        return [rank, item.get("content_key") or item.get("content_id"),
                f"{item.get('avg_value', 0):.1f}" if item.get("avg_value") is not None else "-",
                fmt_int(item.get("n_viewers"))]
    if key == "peak_hours_top10":
        return [rank, f"{item.get('hour')}시", fmt_int(item.get("n_actions"))]
    if key == "heavy_spenders_top10":
        return [rank, item.get("user_id"),
                f"{fmt_int(item.get('total_spend'))}원" if item.get("total_spend") else "-",
                fmt_int(item.get("n_purchases"))]
    if key == "repeat_buyers_top10":
        return [rank, item.get("user_id"),
                item.get("content_key") or item.get("content_id"),
                fmt_int(item.get("n_repeats"))]
    if key == "bestseller_content_top10":
        return [rank, item.get("content_key") or item.get("content_id"),
                fmt_int(item.get("n_purchases"))]
    if key == "active_raters_top10":
        return [rank, item.get("user_id"), fmt_int(item.get("n_ratings")),
                f"★{item.get('avg_rating', 0) / 2:.2f}"]
    if key == "highly_rated_content_top10":
        return [rank, item.get("content_key") or item.get("content_id"),
                f"★{item.get('avg_rating', 0) / 2:.2f}",
                fmt_int(item.get("n_ratings"))]
    if key == "most_disliked_content_top10":
        return [rank, item.get("content_key") or item.get("content_id"),
                fmt_int(item.get("n_lowest_ratings"))]
    if key == "meh_heavy_users_top10":
        return [rank, item.get("user_id"), fmt_int(item.get("n_mehs"))]
    if key == "low_rating_heavy_users_top10":
        return [rank, item.get("user_id"), fmt_int(item.get("n_low_ratings"))]
    if key == "high_neg_ratio_content_top10":
        return [rank, item.get("content_key") or item.get("content_id"),
                fmt_pct(item.get("neg_ratio")),
                f"{fmt_int(item.get('n_neg'))}/{fmt_int(item.get('n_pos'))}"]
    # 기본 — 모든 값 그대로
    return [rank] + list(item.values())


def render(results: dict, filter_keys: list[str] | None = None) -> str:
    """§Appendix. filter_keys 주면 그 키들만 렌더링."""
    cs = results.get("case_studies", {})
    if not cs:
        return ""

    keys = filter_keys if filter_keys else list(cs.keys())
    parts = []
    for key in keys:
        items = cs.get(key)
        if not items:
            continue
        title, headers = CASE_TITLES.get(key, (key, ["#"] + list(items[0].keys())))
        rows = [_extract_row(key, i, item) for i, item in enumerate(items)]
        parts.append(f"### {title}\n\n{md_table(headers, rows)}\n")

    if not parts:
        return ""

    return "## 📎 Appendix — Case Studies\n\n" + "\n".join(parts)
