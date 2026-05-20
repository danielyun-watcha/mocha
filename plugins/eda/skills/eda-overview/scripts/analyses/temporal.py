"""일별 / 월별 시청량."""
import pandas as pd


def run(df: pd.DataFrame, info: dict, ts) -> dict:
    """반환: {'daily_volume': {...}, 'monthly_volume': {...}}
    timestamp 없으면 빈 dict."""
    if ts is None or ts.isna().all():
        return {}

    df2 = df.copy()
    df2["_ts"] = ts
    df2 = df2.dropna(subset=["_ts"])
    if len(df2) == 0:
        return {}

    daily = df2.groupby(df2["_ts"].dt.date).size()
    monthly = df2.groupby(df2["_ts"].dt.to_period("M").astype(str)).size()

    return {
        "daily_volume": {str(k): int(v) for k, v in daily.items()},
        "monthly_volume": {k: int(v) for k, v in monthly.items()},
    }
