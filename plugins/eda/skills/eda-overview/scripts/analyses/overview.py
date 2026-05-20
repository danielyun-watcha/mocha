"""기본 통계 + RecSys 핵심 지표 (sparsity, density, interactions per user/item)."""
import pandas as pd


def run(df: pd.DataFrame, info: dict, ts) -> dict:
    """analysis_results.json의 'overview' 키 생성."""
    n_rows = int(len(df))
    user_col = info["user_col"]
    item_col = info["item_col"]
    n_users = int(df[user_col].nunique()) if user_col in df.columns else 0
    n_items = int(df[item_col].nunique()) if item_col in df.columns else 0

    # interactions per user/item
    rows_per_user_mean = round(n_rows / max(n_users, 1), 2)
    rows_per_user_median = float(df[user_col].value_counts().median()) if user_col in df.columns else 0
    rows_per_item_mean = round(n_rows / max(n_items, 1), 2)
    rows_per_item_median = float(df[item_col].value_counts().median()) if item_col in df.columns else 0

    # Sparsity / density — RecSys 핵심 지표
    matrix_size = n_users * n_items if n_users and n_items else 0
    density_pct = round(n_rows / matrix_size * 100, 4) if matrix_size else 0
    sparsity_pct = round(100 - density_pct, 4)

    section = {
        "domain": info.get("domain"),
        "main_file": info.get("main_file"),
        "n_rows": n_rows,
        "n_users": n_users,
        "n_contents": n_items,
        "rows_per_user_mean": rows_per_user_mean,
        "rows_per_user_median": rows_per_user_median,
        "rows_per_item_mean": rows_per_item_mean,
        "rows_per_item_median": rows_per_item_median,
        "density_pct": density_pct,
        "sparsity_pct": sparsity_pct,
    }

    # 기간 (timestamp 있으면)
    if ts is not None and ts.notna().any():
        ts_clean = ts.dropna()
        section["date_range"] = [str(ts_clean.min().date()), str(ts_clean.max().date())]
        section["span_days"] = int((ts_clean.max() - ts_clean.min()).days)

    return {"overview": section}
