"""Common helpers for eda-overview analyses."""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd


DOMAIN_ROOTS = {
    "graph_modeling", "rec_galaxy", "rec_adult",
    "rating_prediction", "next_watch", "next_purchase",
    "next_adult", "next_slate", "user_bert", "user_bert_adult",
    "adult_foundation", "tutorial",
}

# 도메인 → key_metric (사용자가 brief에 명시 안 했을 때 fallback)
DOMAIN_KEY_METRIC = {
    "graph_modeling": "play",
    "next_watch": "play",
    "user_bert": "play",
    "next_purchase": "buy",
    "rec_adult": "buy",
    "user_bert_adult": "buy",
    "adult_foundation": "buy",
    "next_adult": "buy",
    "rec_galaxy": "rate",
    "rating_prediction": "rate",
}

KEY_METRIC_LABEL = {
    "play": "Play (시청)",
    "buy": "Buy (구매·rental)",
    "rate": "Rate (별점)",
}

# content_type ID → 사람 읽는 라벨 (도메인 공통)
CONTENT_TYPE_LABELS = {
    1: "Movie", 2: "Series", 3: "Webtoon", 4: "Book",
    "MOVIE": "Movie", "TV_SEASON": "Series",
    "WEBTOON": "Webtoon", "BOOK": "Book",
}


def label_content_type(t):
    """raw type id → 라벨. 매핑 없으면 'type_{id}'."""
    return CONTENT_TYPE_LABELS.get(t, f"type_{t}")

MAIN_FILE_CANDIDATES = [
    "train.ftr",       # 가장 흔함
    "adults.ftr",      # rec_adult
    "ratings.ftr",     # rating_prediction
    "watch_logs.ftr",  # next_watch
    "valid.ftr",
    "test.ftr",
]


def detect_domain(data_path: Path) -> dict:
    """data_path → {domain, main_file, main_value_col, type_col, ts_col}."""
    parts = data_path.resolve().parts
    domain = next((p for p in parts if p in DOMAIN_ROOTS), None)

    main_file = None
    for cand in MAIN_FILE_CANDIDATES:
        if (data_path / cand).exists():
            main_file = cand
            break

    # behavior_logs 케이스 — 가장 최근 ftr
    if main_file is None:
        ftrs = sorted(data_path.glob("*.ftr"))
        if ftrs:
            main_file = ftrs[-1].name

    return {
        "domain": domain,
        "main_file": main_file,
        "main_value_col": "value",
        "type_col": "content_type",
        "ts_col": "updated_at",
        "user_col": "user_id",
        "item_col": "content",
    }


def load_main(data_path: Path, info: dict) -> pd.DataFrame:
    """Main file 로드."""
    if info["main_file"] is None:
        raise FileNotFoundError(f"No main file found in {data_path}")
    p = data_path / info["main_file"]
    if p.suffix in (".ftr", ".feather"):
        return pd.read_feather(p)
    if p.suffix == ".parquet":
        return pd.read_parquet(p)
    raise ValueError(f"Unsupported main file: {p}")


def load_or_create_results(out_path: Path, append: bool) -> dict:
    """기존 결과 로드 (--append) 또는 빈 dict."""
    if append and out_path.exists():
        import json
        return json.loads(out_path.read_text())
    return {}


def save_results(results: dict, out_path: Path) -> None:
    """결과 JSON 저장."""
    import json
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))


def build_meta(data_path: Path, info: dict, df: pd.DataFrame,
               ts: pd.Series | None, brief: dict | None = None) -> dict:
    """PANDA "조회 기준" 블록 + key_metric (도메인 KPI).

    Returns dict with keys:
        domain, data_path, main_file, n_rows, n_cols, columns,
        period_start, period_end, n_days, generated_at, key_metric, key_metric_label,
        analysis_goal (brief에서)
    """
    kst = timezone(timedelta(hours=9))
    domain = info.get("domain")
    # key_metric: brief에 명시되었으면 우선, 없으면 도메인 매핑
    key_metric = (brief or {}).get("key_metric") or DOMAIN_KEY_METRIC.get(domain)
    # data_path sanitize — 홈 디렉토리 / 절대경로 leak 방지. /archive 등 prefix만.
    path_str = str(data_path)
    # /archive/X/Y/ 같은 형식 보존, 그 외엔 도메인/파일만
    if "/archive/" in path_str:
        sanitized_path = "/archive/" + path_str.split("/archive/", 1)[1]
    elif domain:
        sanitized_path = f"{domain}/{info.get('main_file', '?')}"
    else:
        sanitized_path = info.get("main_file", "?")
    meta = {
        "domain": domain,
        "data_path": sanitized_path,
        "main_file": info.get("main_file"),
        "n_rows": int(len(df)),
        "n_cols": int(df.shape[1]),
        "columns": list(df.columns),
        "generated_at": datetime.now(kst).isoformat(timespec="seconds"),
        "key_metric": key_metric,
        "key_metric_label": KEY_METRIC_LABEL.get(key_metric, key_metric),
    }
    goal = (brief or {}).get("goal") or (brief or {}).get("research_question")
    if goal:
        meta["analysis_goal"] = goal
    if ts is not None:
        ts_clean = ts.dropna()
        if len(ts_clean) > 0:
            start = ts_clean.min()
            end = ts_clean.max()
            meta["period_start"] = str(start.date()) if hasattr(start, "date") else str(start)
            meta["period_end"] = str(end.date()) if hasattr(end, "date") else str(end)
            try:
                meta["n_days"] = int((end - start).days)
            except (TypeError, AttributeError):
                pass
    return meta


def detect_timestamp(df: pd.DataFrame, info: dict) -> pd.Series | None:
    """timestamp 컬럼을 datetime으로 변환해 반환. **KST(+9h) 보정 포함**.

    Watcha 데이터는 UTC unix timestamp로 저장되므로 분석/리포트의 시간대 해석
    (점심대/저녁대 등) 정확도를 위해 항상 KST로 변환.
    """
    col = info.get("ts_col")
    if col not in df.columns:
        for cand in ("updated_at", "created_at", "timestamp", "ts"):
            if cand in df.columns:
                col = cand
                break
        else:
            return None
    s = df[col]
    if pd.api.types.is_numeric_dtype(s):
        # unix timestamp → UTC → KST (+9h)
        ts_utc = pd.to_datetime(s, unit="s", errors="coerce")
        return ts_utc + pd.Timedelta(hours=9)
    return pd.to_datetime(s, errors="coerce")
