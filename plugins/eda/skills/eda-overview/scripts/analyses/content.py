"""콘텐츠 타입 분포 — 단일 타입이면 자동 skip."""
import pandas as pd

from ._common import CONTENT_TYPE_LABELS


def run(df: pd.DataFrame, info: dict, ts) -> dict:
    """반환: {'content_type': {...}} (단일 타입 도메인이면 빈 dict)."""
    type_col = info.get("type_col", "content_type")
    if type_col not in df.columns:
        return {}

    vc = df[type_col].value_counts()
    if len(vc) < 2:
        # 단일 타입 도메인 (예: rec_adult) — skip
        return {}

    n_rows = len(df)
    out = {}
    for type_id, count in vc.items():
        label = CONTENT_TYPE_LABELS.get(type_id, f"type_{type_id}")
        out[f"{label}_pct"] = round(count / n_rows * 100, 2)
        out[f"{label}_n"] = int(count)

    return {"content_type": out}
