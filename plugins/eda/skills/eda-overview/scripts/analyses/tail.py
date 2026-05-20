"""Lorenz curve + Pareto top k% + Gini (single source of truth)."""
import numpy as np
import pandas as pd


def compute_gini(x_pct: list, y_pct: list) -> float | None:
    """Lorenz curve의 x_pct·y_pct → Gini coefficient (descending sort 대응).

    EDA agent 시스템 내 **유일한 Gini 계산 함수**. 다른 모듈에서는 JSON의 'gini' 키를 읽기만 함.
    """
    if not x_pct or not y_pct or len(x_pct) != len(y_pct) or len(x_pct) < 2:
        return None
    area = sum((x_pct[i] - x_pct[i-1]) * (y_pct[i] + y_pct[i-1]) / 2
               for i in range(1, len(x_pct)))
    # x_pct가 0-100 스케일이면 정규화
    area_norm = area / (100 * 100) if max(x_pct) > 1.5 else area
    # Lorenz가 ascending이면 area < 0.5, descending이면 > 0.5 → 둘 다 대응
    return round(abs(1 - 2 * area_norm), 4)


def run(df: pd.DataFrame, info: dict, ts) -> dict:
    """반환: {'lorenz': {...}, 'pareto_long_tail': {...}, 'gini': float}"""
    item_col = info["item_col"]
    if item_col not in df.columns:
        return {}

    pop = df[item_col].value_counts().sort_values(ascending=False).values
    n = len(pop)
    if n < 2:
        return {}

    total = pop.sum()
    cum = np.cumsum(pop) / total

    # Lorenz curve sample (100 points)
    sample_idx = np.linspace(0, n - 1, min(100, n)).astype(int)
    lorenz_x = ((sample_idx + 1) / n * 100).round(2).tolist()
    lorenz_y = (cum[sample_idx] * 100).round(2).tolist()

    # Pareto top k%
    pareto = {}
    for pct, label in [(0.01, "top1pct"), (0.05, "top5pct"),
                       (0.10, "top10pct"), (0.20, "top20pct")]:
        k = max(1, int(np.ceil(n * pct)))
        share = float(cum[k - 1] * 100)
        pareto[label] = round(share, 2)

    # Gini — single source of truth
    gini = compute_gini(lorenz_x, lorenz_y)

    return {
        "lorenz": {"x_pct": lorenz_x, "y_pct": lorenz_y},
        "pareto_long_tail": pareto,
        "gini": gini,
    }
