"""Main numeric column (value/rating 등) 분포."""
import numpy as np
import pandas as pd


# 도메인별 value 구간 buckets
DEFAULT_BUCKETS = {
    "rating_prediction": [(1, 2, "★0.5"), (2, 3, "★1.0"), (3, 4, "★1.5"),
                          (4, 5, "★2.0"), (5, 6, "★2.5"), (6, 7, "★3.0"),
                          (7, 8, "★3.5"), (8, 9, "★4.0"), (9, 10, "★4.5"),
                          (10, 11, "★5.0")],
    # 시청률 (value = time × 10 / running_time)
    "watch_value": [(0, 5, "<50% 시청"), (5, 10, "50~100% 시청"),
                    (10, 50, "1~5회"), (50, 100, "5~10회"),
                    (100, 1_000_000, "10회+")],
}


def _detect_bucket_scheme(values, domain: str | None) -> str:
    """value 범위와 도메인을 보고 bucket 체계 선택."""
    if domain == "rating_prediction":
        return "rating_prediction"
    # value 범위 (시청률 vs 평점 자동 판단)
    if values.max() <= 10 and values.min() >= 1:
        return "rating_prediction"
    return "watch_value"


def run(df: pd.DataFrame, info: dict, ts) -> dict:
    """반환: {'value_buckets_pct': {...}, 'value_describe': {...}, 'value_boxplot': {...}}"""
    col = info["main_value_col"]
    if col not in df.columns:
        return {}

    v = df[col].astype(float)
    n = len(v)
    if n == 0:
        return {}

    # Describe
    describe = {
        "n": int(n),
        "mean": float(v.mean()),
        "median": float(v.median()),
        "std": float(v.std()) if n > 1 else 0,
        "min": float(v.min()),
        "max": float(v.max()),
    }
    # Quartile (boxplot에 사용)
    boxplot = {
        "p5": float(np.percentile(v, 5)),
        "q1": float(np.percentile(v, 25)),
        "median": float(np.median(v)),
        "q3": float(np.percentile(v, 75)),
        "p95": float(np.percentile(v, 95)),
        "n": int(n),
    }

    # Buckets
    scheme = _detect_bucket_scheme(v, info.get("domain"))
    buckets = DEFAULT_BUCKETS[scheme]
    bucket_pct = {}
    for lo, hi, label in buckets:
        cnt = int(((v >= lo) & (v < hi)).sum())
        bucket_pct[label] = round(cnt / n * 100, 2)

    # Content_type별 boxplot (있으면)
    type_boxplot = {}
    type_col = info.get("type_col")
    if type_col in df.columns and df[type_col].nunique() >= 2:
        from ._common import CONTENT_TYPE_LABELS
        for type_id, group in df.groupby(type_col):
            label = CONTENT_TYPE_LABELS.get(type_id, f"type_{type_id}")
            gv = group[col].astype(float)
            if len(gv) > 0:
                type_boxplot[label] = {
                    "p5": float(np.percentile(gv, 5)),
                    "q1": float(np.percentile(gv, 25)),
                    "median": float(np.median(gv)),
                    "q3": float(np.percentile(gv, 75)),
                    "p95": float(np.percentile(gv, 95)),
                    "n": int(len(gv)),
                }

    result = {
        "value_describe": describe,
        "value_buckets_pct": bucket_pct,
        "value_boxplot_overall": boxplot,
    }
    if type_boxplot:
        result["value_boxplot"] = type_boxplot
    return result
