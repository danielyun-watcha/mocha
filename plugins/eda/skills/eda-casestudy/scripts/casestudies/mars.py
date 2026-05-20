"""mars 도메인 case study — graph_modeling, next_watch, next_purchase, user_bert 통합."""
import numpy as np
import pandas as pd

from ._common import top_n_users, top_n_contents, load_contents_meta, safe_cid, safe_content_key


def run(df: pd.DataFrame, data_path, top_n: int = 10) -> dict:
    """mars 도메인 case study + suggestions."""
    cases = {}
    suggestions = []

    contents_map = load_contents_meta(data_path)
    user_col = "user_id"
    content_col = "content"
    value_col = "value"

    # 1. 시청량 TOP N 유저 (행수 + value 누적)
    user_rows = df[user_col].value_counts().head(top_n)
    user_value_sum = df.groupby(user_col)[value_col].sum()

    heavy_users = []
    for uid in user_rows.index:
        heavy_users.append({
            "user_id": int(uid),
            "metric": "시청 건수 / value 누적",
            "n_rows": int(user_rows[uid]),
            "value_sum": round(float(user_value_sum.loc[uid]), 1),
        })
    cases["heavy_users_top10"] = heavy_users

    # 2. 다회차 시청 TOP N 콘텐츠 (평균 value 높은 — 즉 자주 본 콘텐츠)
    pop = df.groupby(content_col).agg(
        n_viewers=(user_col, "nunique"),
        avg_value=(value_col, "mean"),
        max_value=(value_col, "max"),
    )
    # 50명 이상이 본 콘텐츠 중 avg_value top
    pop_filt = pop[pop["n_viewers"] >= 50].nlargest(top_n, "avg_value")

    loyal_content = []
    for cid in pop_filt.index:
        loyal_content.append({
            "content_id": safe_cid(cid),
            "content_key": safe_content_key(contents_map, cid),
            "metric": "평균 value (다회차)",
            "avg_value": round(float(pop_filt.loc[cid, "avg_value"]), 1),
            "n_viewers": int(pop_filt.loc[cid, "n_viewers"]),
            "max_value": round(float(pop_filt.loc[cid, "max_value"]), 1),
        })
    cases["loyal_content_top10"] = loyal_content

    # 3. (timestamp 있으면) 시간대 TOP — KST 보정 (Watcha 데이터는 UTC)
    if "updated_at" in df.columns:
        ts_utc = pd.to_datetime(df["updated_at"], unit="s", errors="coerce").dropna()
        ts_kst = ts_utc + pd.Timedelta(hours=9)
        hour_dist = ts_kst.dt.hour.value_counts().head(top_n)
        peak_hour = int(hour_dist.idxmax())
        peak_count = int(hour_dist.max())
        cases["peak_hours_top10"] = [
            {"hour": int(h), "n_actions": int(c)}
            for h, c in hour_dist.items()
        ]
        # 시간대 그룹 자동 인식 (KST 기준)
        if 18 <= peak_hour <= 23 or peak_hour <= 2:
            group = "저녁/심야"
        elif 11 <= peak_hour <= 15:
            group = "점심대"
        elif 6 <= peak_hour <= 10:
            group = "아침"
        else:
            group = ""
        group_part = f" ({group})" if group else ""
        suggestions.append(
            f"시청 피크 시간대 KST {peak_hour}시{group_part} — {peak_count:,}건. 시간대 가중 학습 검토 가치."
        )

    # 4. Outlier 유저 (suggestion)
    p99 = float(np.percentile(df[user_col].value_counts().values, 99))
    p99_x10 = p99 * 10
    extreme_users = user_rows[user_rows > p99_x10]
    if len(extreme_users) > 0:
        suggestions.append(
            f"활동량 p99의 10배 초과 유저 {len(extreme_users)}명 — 봇/공유계정 의심, 별도 검증 권장"
        )

    # 5. 콘텐츠 value 극단치 (suggestion)
    if len(pop) > 0:
        high_avg = pop[pop["avg_value"] > 5000]
        if len(high_avg) > 0:
            suggestions.append(
                f"평균 value 5000+ 콘텐츠 {len(high_avg)}개 — 학습 노이즈 가능, 시리즈 시즌 누적 확인"
            )

    return {"case_studies": cases, "analysis_suggestions": suggestions}
