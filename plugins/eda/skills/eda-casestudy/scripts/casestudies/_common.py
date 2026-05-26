"""Common helpers for case study modules."""
from pathlib import Path

import pandas as pd
import numpy as np


# 도메인 그룹 매핑 (next_watch/purchase/user_bert/graph_modeling 모두 mars로)
DOMAIN_GROUP = {
    "graph_modeling": "mars",
    "next_watch": "mars",
    "next_purchase": "mars",
    "user_bert": "mars",
    "rec_galaxy": "galaxy",
    "rating_prediction": "galaxy",
    "rec_adult": "adult",
    "user_bert_adult": "adult",
    "adult_foundation": "adult",
}

MAIN_FILE_CANDIDATES = [
    "train.ftr", "adults.ftr", "ratings.ftr",
    "watch_logs.ftr", "valid.ftr", "test.ftr",
    "hard_neg_edges.ftr",
]

# 도메인별 main file 우선순위 — case study용 실데이터 (sequence padded 학습포맷 회피)
DOMAIN_MAIN_PRIORITY = {
    "galaxy": ["ratings.ftr", "valid.ftr", "test.ftr", "train.ftr"],
    "adult": ["adults.ftr", "train.ftr"],
    "negative": ["hard_neg_edges.ftr", "train.ftr"],
    "mars": ["train.ftr", "watch_logs.ftr", "valid.ftr"],
}


def safe_cid(cid):
    """content id 안전 변환 — string ('2:13811') 그대로 유지, int면 int."""
    try:
        return int(cid)
    except (ValueError, TypeError):
        return str(cid)


def safe_content_key(contents_map, cid):
    """contents_map lookup. string cid (예: '10:3680') 면 그 자체가 content_key."""
    # 이미 X:Y format string이면 그대로 사용
    if isinstance(cid, str):
        return cid
    if contents_map is None:
        return None
    try:
        return contents_map.get(int(cid))
    except (ValueError, TypeError):
        return None


def detect_domain_group(data_path: Path) -> str:
    """data_path → "mars" | "galaxy" | "adult" | "negative" | "unknown"."""
    parts = data_path.resolve().parts
    path_str = str(data_path).lower()

    # Negative 검출 — graph_modeling/exp-*meh* 패턴
    if "meh" in path_str or "negative" in path_str:
        return "negative"

    for part in parts:
        if part in DOMAIN_GROUP:
            return DOMAIN_GROUP[part]

    return "unknown"


def load_main(data_path: Path, domain_group: str | None = None):
    """Main file 로드. 도메인 지정 시 도메인별 우선순위 적용 (sequence padded 학습포맷 회피)."""
    priority = DOMAIN_MAIN_PRIORITY.get(domain_group, MAIN_FILE_CANDIDATES)
    for cand in priority:
        p = data_path / cand
        if p.exists():
            return pd.read_feather(p), cand
    # behavior_logs 케이스 — 가장 최근 ftr
    ftrs = sorted(data_path.glob("*.ftr"))
    if ftrs:
        return pd.read_feather(ftrs[-1]), ftrs[-1].name
    raise FileNotFoundError(f"No data file in {data_path}")


def load_contents_meta(data_path: Path) -> dict | None:
    """contents.pkl 로드해서 idx → content_key 매핑 반환. 없으면 None.
    list 형식 ['1:1', '1:10', ...] 또는 dict 형식 {'1:1': 2, ...} 둘 다 지원.
    """
    p = data_path / "contents.pkl"
    if not p.exists():
        return None
    import pickle
    with open(p, "rb") as f:
        contents = pickle.load(f)
    if isinstance(contents, list):
        # SPECIAL_INDICES=[0] → 1-indexed
        return {i + 1: v for i, v in enumerate(contents)}
    if isinstance(contents, dict):
        # forward map {key: idx} → reverse
        return {v: k for k, v in contents.items()}
    return None


def load_contents_forward(data_path: Path) -> dict | None:
    """content_key (str) → idx (int) 매핑. adult 가격 lookup chain용."""
    p = data_path / "contents.pkl"
    if not p.exists():
        return None
    import pickle
    with open(p, "rb") as f:
        contents = pickle.load(f)
    if isinstance(contents, dict):
        return contents
    if isinstance(contents, list):
        return {v: i + 1 for i, v in enumerate(contents)}
    return None


def top_n_users(df: pd.DataFrame, user_col: str = "user_id",
                value_col: str | None = None, n: int = 10) -> pd.DataFrame:
    """유저별 TOP N. value_col 있으면 합산, 없으면 행수."""
    if value_col and value_col in df.columns:
        agg = df.groupby(user_col)[value_col].sum().nlargest(n)
        return agg.reset_index().rename(columns={value_col: "metric_value"})
    counts = df[user_col].value_counts().head(n)
    return counts.reset_index().rename(columns={"count": "metric_value"})


def top_n_contents(df: pd.DataFrame, content_col: str = "content",
                   metric: str = "n_viewers", value_col: str = "value",
                   n: int = 10) -> pd.DataFrame:
    """콘텐츠별 TOP N. metric: 'n_viewers' | 'avg_value' | 'sum_value'."""
    if metric == "n_viewers":
        result = df.groupby(content_col).size().nlargest(n)
        return result.reset_index().rename(columns={0: "metric_value"})
    elif metric == "avg_value":
        result = df.groupby(content_col)[value_col].mean().nlargest(n)
        return result.reset_index().rename(columns={value_col: "metric_value"})
    elif metric == "sum_value":
        result = df.groupby(content_col)[value_col].sum().nlargest(n)
        return result.reset_index().rename(columns={value_col: "metric_value"})


def load_or_create_results(out_path: Path, append: bool) -> dict:
    if append and out_path.exists():
        import json
        return json.loads(out_path.read_text())
    return {}


def save_results(results: dict, out_path: Path) -> None:
    import json
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
