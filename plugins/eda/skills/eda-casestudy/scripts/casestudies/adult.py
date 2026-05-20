"""adult (rec_adult) case study — 큰손, 재구매, 헤비 buyer."""
import pickle
from pathlib import Path

import pandas as pd

from ._common import load_contents_meta, load_contents_forward, safe_cid, safe_content_key


def _load_price_map(data_path: Path):
    """CONTENT_TO_PRICE.pkl 로드. nested {'rental': {...}, 'possession': {...}} 평탄화."""
    candidates = ["CONTENT_TO_PRICE.pkl", "PRICE_TO_BIN_CONVERT_MAP.pkl"]
    for cand in candidates:
        p = data_path / cand
        if p.exists():
            with open(p, "rb") as f:
                m = pickle.load(f)
            # nested dict {service: {idx: price}} → 평탄화
            if isinstance(m, dict) and m and isinstance(next(iter(m.values())), dict):
                flat = {}
                for sub in m.values():
                    flat.update(sub)
                return flat
            return m
    return None


def run(df: pd.DataFrame, data_path, top_n: int = 10) -> dict:
    cases = {}
    suggestions = []

    contents_map = load_contents_meta(data_path)
    contents_forward = load_contents_forward(data_path)
    price_map = _load_price_map(data_path)
    user_col = "user_id"
    content_col = "content"

    # 1. 큰손 TOP N — 매출 (가격 매핑 있으면) 또는 행수
    # adults.ftr content는 string('10:3680') → contents_forward로 idx 변환 후 price lookup
    if price_map and content_col in df.columns:
        df = df.copy()
        if contents_forward and df[content_col].dtype == object:
            df["_idx"] = df[content_col].map(contents_forward)
            df["_price"] = df["_idx"].map(price_map).fillna(0)
        else:
            df["_price"] = df[content_col].map(price_map).fillna(0)
        user_spend = df.groupby(user_col)["_price"].sum().nlargest(top_n)
        user_n = df[user_col].value_counts()

        heavy_spenders = []
        for uid in user_spend.index:
            heavy_spenders.append({
                "user_id": int(uid),
                "metric": "총 매출 / 구매 수",
                "total_spend": round(float(user_spend.loc[uid])),
                "n_purchases": int(user_n.get(uid, 0)),
            })
        cases["heavy_spenders_top10"] = heavy_spenders
    else:
        # 가격 정보 없으면 행수 기반
        user_n = df[user_col].value_counts().head(top_n)
        cases["heavy_users_top10"] = [
            {"user_id": int(uid), "metric": "구매·시청 건수", "n_actions": int(c)}
            for uid, c in user_n.items()
        ]
        suggestions.append(
            "가격 매핑(CONTENT_TO_PRICE.pkl) 없어 행수 기반으로만 추출 — 매출 분석은 별도 데이터 필요"
        )

    # 2. 재구매 TOP N — 동일 (user, content) 반복
    repeat = df.groupby([user_col, content_col]).size()
    repeat_top = repeat[repeat > 1].nlargest(top_n)
    repeat_buyers = []
    for (uid, cid), cnt in repeat_top.items():
        repeat_buyers.append({
            "user_id": int(uid),
            "content_id": safe_cid(cid),
            "content_key": safe_content_key(contents_map, cid),
            "n_repeats": int(cnt),
        })
    cases["repeat_buyers_top10"] = repeat_buyers

    # 3. 헤비 buyer 콘텐츠 TOP N — 가장 많이 팔린
    content_sales = df[content_col].value_counts().head(top_n)
    bestseller = []
    for cid, cnt in content_sales.items():
        bestseller.append({
            "content_id": safe_cid(cid),
            "content_key": safe_content_key(contents_map, cid),
            "metric": "구매·시청 수",
            "n_purchases": int(cnt),
        })
    cases["bestseller_content_top10"] = bestseller

    # Suggestions
    user_n_full = df[user_col].value_counts()
    if user_n_full.max() > user_n_full.quantile(0.99) * 5:
        suggestions.append(
            f"유저 {user_n_full.idxmax()} 활동량이 p99의 5배 초과 — 큰손 vs 봇 검증 필요"
        )

    # 재구매율
    n_unique_pairs = repeat.shape[0]
    n_repeats = (repeat > 1).sum()
    if n_unique_pairs > 0:
        repeat_rate = n_repeats / n_unique_pairs * 100
        if repeat_rate > 10:
            suggestions.append(
                f"재구매율 {repeat_rate:.1f}% — 충성 콘텐츠 패턴 별도 분석 가치"
            )

    return {"case_studies": cases, "analysis_suggestions": suggestions}
