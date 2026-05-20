"""negative case study — MEH 헤비, 저평점 헤비, 부정 비율 콘텐츠."""
from pathlib import Path

import pandas as pd

from ._common import load_contents_meta, safe_cid, safe_content_key


def run(df: pd.DataFrame, data_path, top_n: int = 10) -> dict:
    """hard_neg_edges.ftr 또는 비슷한 부정 데이터 처리."""
    cases = {}
    suggestions = []

    contents_map = load_contents_meta(data_path)
    user_col = "user_id"
    content_col = "content"
    value_col = "value"  # -1 = MEH, 1~5 = 저평점

    # 1. MEH 헤비 TOP N
    meh = df[df[value_col] == -1] if value_col in df.columns else pd.DataFrame()
    if len(meh) > 0:
        meh_top = meh[user_col].value_counts().head(top_n)
        cases["meh_heavy_users_top10"] = [
            {"user_id": int(uid), "metric": "싫어요(MEH) 누름 수", "n_mehs": int(c)}
            for uid, c in meh_top.items()
        ]

    # 2. 저평점 헤비 TOP N (value 1~5)
    low = df[df[value_col].isin([1, 2, 3, 4, 5])] if value_col in df.columns else pd.DataFrame()
    if len(low) > 0:
        low_top = low[user_col].value_counts().head(top_n)
        cases["low_rating_heavy_users_top10"] = [
            {"user_id": int(uid), "metric": "저평점 (★2.5 이하) 매김 수", "n_low_ratings": int(c)}
            for uid, c in low_top.items()
        ]

    # 3. 부정 비율 TOP N 콘텐츠 — train.ftr (positive) 있어야
    train_path = data_path / "train.ftr"
    if train_path.exists():
        train = pd.read_feather(train_path)
        pos = train.groupby(content_col).size().rename("n_pos")
        neg = df.groupby(content_col).size().rename("n_neg")
        merged = pd.concat([pos, neg], axis=1).fillna(0).astype(int)
        merged["neg_ratio"] = merged["n_neg"] / (merged["n_neg"] + merged["n_pos"] + 1)
        # positive ≥ 50인 콘텐츠 중 부정 비율 top
        merged_filt = merged[merged["n_pos"] >= 50].nlargest(top_n, "neg_ratio")
        cases["high_neg_ratio_content_top10"] = [
            {
                "content_id": safe_cid(cid),
                "content_key": safe_content_key(contents_map, cid),
                "metric": "부정 비율 (부정 / (부정+positive))",
                "neg_ratio": round(float(row["neg_ratio"]), 3),
                "n_neg": int(row["n_neg"]),
                "n_pos": int(row["n_pos"]),
            }
            for cid, row in merged_filt.iterrows()
        ]

        # Suggestion: 부정 비율 0.9+ 콘텐츠
        n_extreme = int((merged["neg_ratio"] > 0.9).sum())
        if n_extreme > 5:
            suggestions.append(
                f"부정 비율 90%+ 콘텐츠 {n_extreme}개 — 학습 hard negative pool 우선 후보"
            )

    # 4. MEH 신호 자체 분포 (Gini 등)
    if len(meh) > 0:
        meh_user_counts = meh[user_col].value_counts()
        gini_estimate = 1 - 2 * (meh_user_counts.values.cumsum().mean() / meh_user_counts.values.sum() / len(meh_user_counts))
        if gini_estimate > 0.7:
            suggestions.append(
                f"MEH Gini ~{gini_estimate:.2f} — 헤비 큐레이터 (소수가 대부분 생성), 신호 가중치 조정 검토"
            )

    return {"case_studies": cases, "analysis_suggestions": suggestions}
