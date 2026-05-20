"""데이터 품질 — null, 중복, outlier."""
import numpy as np
import pandas as pd


def run(df: pd.DataFrame, info: dict, ts) -> dict:
    """반환: {'data_quality': {...}}"""
    n = int(len(df))
    if n == 0:
        return {"data_quality": {"n_rows": 0, "notes": ["빈 데이터프레임"]}}

    null_pct = {col: round(df[col].isna().sum() / n * 100, 3)
                for col in df.columns
                if df[col].isna().any()}
    n_duplicates = int(df.duplicated().sum())

    notes = []

    # Sparsity 메시지
    user_col, item_col = info["user_col"], info["item_col"]
    if user_col in df.columns and item_col in df.columns:
        n_u = df[user_col].nunique()
        n_i = df[item_col].nunique()
        sparsity = 1 - n / (n_u * n_i) if n_u * n_i else 0
        if sparsity > 0.99:
            notes.append(f"sparsity {sparsity*100:.2f}% — cold-start 도전적")
        elif sparsity > 0.95:
            notes.append(f"sparsity {sparsity*100:.2f}% — 학습 가능 (RecSys 일반)")

    # value outlier (p99 vs p95 gap)
    col = info["main_value_col"]
    value_outlier = None
    if col in df.columns:
        v = df[col].astype(float)
        p95 = float(np.percentile(v, 95))
        p99 = float(np.percentile(v, 99))
        max_v = float(v.max())
        value_outlier = {"p95": p95, "p99": p99, "max": max_v}
        if max_v > p99 * 10:
            notes.append(f"value max ({max_v:.0f})가 p99 ({p99:.0f})의 10배 이상 — 극단치 의심")

    # null 비율 평가
    if null_pct:
        worst_col = max(null_pct, key=null_pct.get)
        if null_pct[worst_col] > 5:
            notes.append(f"'{worst_col}' null {null_pct[worst_col]}% — 데이터 정제 검토")

    if n_duplicates > 0:
        notes.append(f"중복 {n_duplicates:,}건 — 정제 필요할 수 있음")

    return {
        "data_quality": {
            "n_rows": n,
            "null_pct_by_column": null_pct,
            "n_duplicates": n_duplicates,
            "value_outlier": value_outlier,
            "notes": notes if notes else ["품질 이슈 없음"],
        }
    }
