"""galaxy / rating_prediction case study."""
import numpy as np
import pandas as pd

from ._common import load_contents_meta, safe_cid, safe_content_key


def run(df: pd.DataFrame, data_path, top_n: int = 10) -> dict:
    cases = {}
    suggestions = []

    contents_map = load_contents_meta(data_path)
    user_col = "user_id"
    content_col = "content"
    value_col = "value"

    # 1. rating 최다 매김 TOP N 유저
    user_rating_counts = df[user_col].value_counts().head(top_n)
    user_rating_mean = df.groupby(user_col)[value_col].mean()

    active_raters = []
    for uid in user_rating_counts.index:
        active_raters.append({
            "user_id": int(uid),
            "metric": "rating 매김 건수 / 평균 별점",
            "n_ratings": int(user_rating_counts[uid]),
            "avg_rating": round(float(user_rating_mean.loc[uid]), 2),
        })
    cases["active_raters_top10"] = active_raters

    # 2. 평균 별점 TOP N 콘텐츠 (충분한 평가 수 필터)
    content_stats = df.groupby(content_col).agg(
        n_ratings=(user_col, "size"),
        avg_rating=(value_col, "mean"),
        median_rating=(value_col, "median"),
    )
    # 100명 이상 평가받은 콘텐츠 중
    content_filt = content_stats[content_stats["n_ratings"] >= 100]
    top_rated = content_filt.nlargest(top_n, "avg_rating")

    high_rated_content = []
    for cid in top_rated.index:
        high_rated_content.append({
            "content_id": safe_cid(cid),
            "content_key": safe_content_key(contents_map, cid),
            "metric": "평균 별점 (100명+ 평가)",
            "avg_rating": round(float(top_rated.loc[cid, "avg_rating"]), 2),
            "n_ratings": int(top_rated.loc[cid, "n_ratings"]),
        })
    cases["highly_rated_content_top10"] = high_rated_content

    # 3. 평점 분포 극단 — 가장 많이 ★0.5 받은 콘텐츠
    if value_col in df.columns:
        is_lowest = df[value_col] == df[value_col].min()
        lowest_ratings = df[is_lowest][content_col].value_counts().head(top_n)
        most_disliked = []
        for cid, cnt in lowest_ratings.items():
            most_disliked.append({
                "content_id": safe_cid(cid),
                "content_key": safe_content_key(contents_map, cid),
                "metric": f"★{df[value_col].min() * 0.5} 평점 수 (최저)",
                "n_lowest_ratings": int(cnt),
            })
        cases["most_disliked_content_top10"] = most_disliked

    # Suggestions
    # - 평점 5.0 콘텐츠 다수 (suspicious)
    perfect_score = content_filt[content_filt["avg_rating"] == content_filt["avg_rating"].max()]
    if len(perfect_score) >= 5:
        suggestions.append(
            f"평균 별점 만점 콘텐츠 {len(perfect_score)}개 — 평점 데이터 신뢰도 검증 필요 (편향 가능)"
        )

    # - rating 1건만 매긴 유저 비율 (cold-start)
    one_rating = (df[user_col].value_counts() == 1).sum()
    total_users = df[user_col].nunique()
    if one_rating / total_users > 0.5:
        suggestions.append(
            f"1건만 평가한 유저 {one_rating:,}명 ({one_rating/total_users*100:.0f}%) — cold-start 시청자 비중 큼"
        )

    return {"case_studies": cases, "analysis_suggestions": suggestions}
