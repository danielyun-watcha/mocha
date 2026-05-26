"""Cross-tab 분석 — key_metric을 깊이 있게 보기.

분석:
1. content_type × value (Series vs Movie의 평균/중앙값 value)
2. 시간대 × content_type (시간대별 type 비중)
3. 유저 활동 segment (light/medium/heavy 분포)
4. Top X% 콘텐츠가 어떤 type인지
"""
import numpy as np
import pandas as pd

from ._common import label_content_type


def run(df: pd.DataFrame, info: dict, ts: pd.Series | None) -> dict:
    """cross-tab 분석들 — 가능한 것만 실행."""
    out = {}
    user_col = info.get("user_col", "user_id")
    item_col = info.get("item_col", "content")
    value_col = info.get("main_value_col", "value")
    type_col = info.get("type_col", "content_type")

    has_value = value_col in df.columns
    has_type = type_col in df.columns
    has_ts = ts is not None

    # 1. content_type × value
    if has_type and has_value:
        agg = df.groupby(type_col)[value_col].agg(
            n="size", mean="mean", median="median", sum="sum"
        ).round(2)
        total = agg["sum"].sum()
        agg["pct_of_total"] = (agg["sum"] / total * 100).round(2)
        agg = agg.reset_index()
        # type id → label
        agg[type_col] = agg[type_col].apply(label_content_type)
        out["value_by_type"] = agg.to_dict(orient="records")

    # 2. 시간대 × content_type
    if has_type and has_ts:
        df2 = df[[type_col]].copy()
        df2["hour"] = ts.dt.hour
        df2["_type_label"] = df2[type_col].apply(label_content_type)
        ct = pd.crosstab(df2["hour"], df2["_type_label"], normalize="index") * 100
        ct = ct.round(2)
        out["type_by_hour"] = ct.reset_index().to_dict(orient="records")

    # 3. 유저 활동 segment (행수 기준)
    if user_col in df.columns:
        per_user = df[user_col].value_counts()
        segments = {
            "Light (1-5건)": int(((per_user >= 1) & (per_user <= 5)).sum()),
            "Medium (6-20건)": int(((per_user >= 6) & (per_user <= 20)).sum()),
            "Heavy (21-49건)": int(((per_user >= 21) & (per_user <= 49)).sum()),
            "Power (50건+)": int((per_user >= 50).sum()),
        }
        total_users = int(per_user.shape[0])
        seg_pct = {k: round(v / total_users * 100, 2) for k, v in segments.items()}
        out["user_segments"] = {
            "counts": segments,
            "pct": seg_pct,
            "total_users": total_users,
        }

    # 4. Top X% 콘텐츠의 type 분포
    if has_type and item_col in df.columns:
        item_n = df.groupby(item_col).size().sort_values(ascending=False)
        n_items = len(item_n)
        item_type = df.groupby(item_col)[type_col].agg(lambda s: s.mode().iat[0] if len(s) else None)
        # type id → label 변환
        item_type = item_type.apply(label_content_type)

        out_top = {}
        for pct, label in [(0.01, "top1pct"), (0.05, "top5pct"), (0.20, "top20pct")]:
            k = max(1, int(n_items * pct))
            top_items = item_n.head(k).index
            type_dist = item_type.reindex(top_items).value_counts(normalize=True) * 100
            out_top[label] = {t: round(float(p), 2) for t, p in type_dist.items()}
        out["top_content_type_dist"] = out_top

    # 5. Value 분위수별 type 분포 (큰 value 콘텐츠는 어떤 type인지)
    if has_type and has_value and item_col in df.columns:
        item_avg = df.groupby(item_col)[value_col].mean()
        item_t = df.groupby(item_col)[type_col].agg(lambda s: s.mode().iat[0] if len(s) else None)
        item_t = item_t.apply(label_content_type)
        merged = pd.DataFrame({"avg_value": item_avg, "type": item_t}).dropna()
        if len(merged) >= 4:
            merged["quartile"] = pd.qcut(merged["avg_value"], 4,
                                          labels=["Q1 (low)", "Q2", "Q3", "Q4 (high)"],
                                          duplicates="drop")
            q_type = (
                merged.groupby("quartile", observed=False)["type"]
                .value_counts(normalize=True)
                .mul(100).round(2).rename("pct").reset_index()
            )
            out["type_by_value_quartile"] = q_type.to_dict(orient="records")

    return out
