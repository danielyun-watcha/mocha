"""§ Cross-tab 분석 — key_metric을 깊이 있게 보기.

eda-overview의 cross.py가 출력한 분석들을 표로 렌더.
§ 주요 인사이트의 distribution 다음, 관점별 인사이트 앞에 들어감.
"""
from ._common import fmt_int, fmt_pct, md_table


def _value_by_type_block(records: list[dict], key_metric_label: str) -> str:
    if not records or len(records) < 2:
        return ""
    lines = [f"### 🎯 콘텐츠 타입별 {key_metric_label} 행동", ""]
    headers = ["타입", "행수", "평균 value", "전체 value 점유"]
    rows = []
    for r in records:
        rows.append([
            r.get("content_type") or "-",
            fmt_int(r.get("n", 0)),
            f"{r.get('mean', 0):.0f}",
            fmt_pct(r.get("pct_of_total", 0)),
        ])
    lines.append(md_table(headers, rows))
    lines.append("")
    # 간결 1줄 — 깊이 해석은 § 도메인 깊이 해석에서
    sorted_recs = sorted(records, key=lambda r: r.get("mean", 0), reverse=True)
    top, low = sorted_recs[0], sorted_recs[-1]
    if top.get("mean") and low.get("mean") and low.get("mean") > 0:
        ratio = top["mean"] / low["mean"]
        n_ratio = top.get("n", 1) / max(low.get("n", 1), 1)
        lines.append(
            f"> **{top['content_type']}** 1건당 평균 value가 **{low['content_type']}** 대비 **{ratio:.2f}배** "
            f"· 행수는 {n_ratio:.2f}배 — engagement 깊이 비대칭"
        )
        lines.append("")
    return "\n".join(lines)


def _type_by_hour_block(records: list[dict], min_diff_pp: float = 3.0) -> str:
    """시간대 × content_type — 차이가 의미 있을 때만 출력 (3%p 이상)."""
    if not records or len(records) < 6:
        return ""
    # 'hour' + type 컬럼들 — int 컬럼명도 str로
    type_keys = [str(k) for k in records[0].keys() if k != "hour"]
    if not type_keys:
        return ""
    # records의 key를 str로 통일
    records = [{str(k) if k != "hour" else "hour": v for k, v in r.items()} for r in records]
    # 점심대 (11-14시) vs 저녁대 (19-22시) 평균 type 비중
    def _avg_for_hours(hours):
        sel = [r for r in records if r.get("hour") in hours]
        if not sel:
            return {}
        return {t: sum(r.get(t, 0) for r in sel) / len(sel) for t in type_keys}

    lunch = _avg_for_hours(range(11, 15))
    evening = _avg_for_hours(range(19, 23))
    if not lunch or not evening:
        return ""
    # 최대 diff가 threshold 미만이면 의미 없는 표 — skip
    max_diff = max((abs(lunch.get(t, 0) - evening.get(t, 0)) for t in type_keys), default=0)
    if max_diff < min_diff_pp:
        return ""  # 시간대별 type 비중 거의 동일 — 보고할 가치 없음
    lines = ["### 🕐 시간대별 콘텐츠 타입 비중", ""]
    headers = ["시간대"] + type_keys
    rows = [
        ["점심대 (11~14시)"] + [fmt_pct(lunch.get(t, 0)) for t in type_keys],
        ["저녁대 (19~22시)"] + [fmt_pct(evening.get(t, 0)) for t in type_keys],
    ]
    lines.append(md_table(headers, rows))
    lines.append("")
    diffs = [(t, lunch.get(t, 0) - evening.get(t, 0)) for t in type_keys]
    diffs.sort(key=lambda x: -abs(x[1]))
    t, d = diffs[0]
    side = "점심대" if d > 0 else "저녁대"
    lines.append(f"> **{t}**가 {side}에서 {abs(d):.1f}%p 더 많이 시청됨 — "
                 f"시간대별 type-aware reranker 검토 가치.")
    lines.append("")
    return "\n".join(lines)


def _user_segments_block(segments: dict, key_metric_label: str) -> str:
    if not segments:
        return ""
    counts = segments.get("counts", {})
    pct = segments.get("pct", {})
    if not counts:
        return ""
    lines = [f"### 👥 유저 활동 segment ({key_metric_label} 기준)", ""]
    headers = ["Segment", "유저 수", "비율"]
    rows = []
    seg_order = ["Light (1-5건)", "Medium (6-20건)", "Heavy (21-49건)", "Power (50건+)"]
    for label in seg_order:
        if label in counts:
            rows.append([label, fmt_int(counts[label]), fmt_pct(pct.get(label, 0))])
    lines.append(md_table(headers, rows))
    lines.append("")
    # 간결 1줄
    dominant = max(((k, v) for k, v in pct.items() if k in seg_order),
                   key=lambda kv: kv[1], default=None)
    if dominant:
        lines.append(f"> **{dominant[0]}** 가 **{dominant[1]:.1f}%** 로 지배적")
        lines.append("")
    return "\n".join(lines)


def _top_content_type_dist_block(dist: dict, overall_type_share: dict) -> str:
    """상위 인기 콘텐츠 vs 전체 type 분포 비교 — 편중 여부 확인."""
    if not dist:
        return ""
    lines = ["### 🏆 상위 인기 콘텐츠의 타입 분포 (전체 대비)", ""]
    all_types = set()
    for d in dist.values():
        all_types.update(d.keys())
    all_types = sorted(all_types)
    headers = ["구간"] + all_types
    rows = []
    # 전체 분포 추가 (baseline)
    if overall_type_share:
        rows.append(["전체 (baseline)"] + [fmt_pct(overall_type_share.get(t, 0)) for t in all_types])
    for label_pct, label_show in [("top1pct", "상위 1%"), ("top5pct", "상위 5%"), ("top20pct", "상위 20%")]:
        d = dist.get(label_pct, {})
        if d:
            rows.append([label_show] + [fmt_pct(d.get(t, 0)) for t in all_types])
    if rows:
        lines.append(md_table(headers, rows))
        lines.append("")
        # 간결 1줄
        top1 = dist.get("top1pct", {})
        if top1 and overall_type_share:
            best = max(top1.items(), key=lambda x: x[1] / max(overall_type_share.get(x[0], 1e-9), 1e-9))
            t, top1_pct = best
            baseline = overall_type_share.get(t, 0)
            if baseline > 0:
                over = top1_pct / baseline
                if over > 1.3:
                    lines.append(
                        f"> 상위 1% 인기 콘텐츠 중 **{t}** {top1_pct:.1f}% — "
                        f"baseline {baseline:.1f}% 대비 **{over:.2f}배** 편중"
                    )
            lines.append("")
    return "\n".join(lines)


def _type_by_quartile_block(records: list[dict]) -> str:
    """Value 분위수별 type 편중 — 의미 있는 패턴(Q1과 Q4 큰 차이)만 보고."""
    if not records:
        return ""
    types = sorted({str(r.get("type")) for r in records if r.get("type") is not None})
    quartiles = ["Q1 (low)", "Q2", "Q3", "Q4 (high)"]
    if len(types) < 2:
        return ""

    # 매트릭스 구성
    matrix = {q: {t: 0.0 for t in types} for q in quartiles}
    for r in records:
        q = str(r.get("quartile"))
        t = str(r.get("type"))
        if q in matrix and t in matrix[q]:
            matrix[q][t] = float(r.get("pct", 0))

    # Q4 (high)에서 가장 비중 큰 type — 큰 value 콘텐츠가 어떤 type인지
    if not all(matrix[q] for q in ["Q1 (low)", "Q4 (high)"]):
        return ""
    q4 = matrix["Q4 (high)"]
    dominant_type, dominant_pct = max(q4.items(), key=lambda x: x[1])
    q1_pct = matrix["Q1 (low)"][dominant_type]
    diff = dominant_pct - q1_pct
    # threshold — Q1↔Q4 차이가 30%p 이상이어야 의미 있음
    if diff < 30:
        return ""

    lines = ["### 📊 Value 분위수별 콘텐츠 타입 분포", ""]
    headers = ["Value 분위수"] + types
    rows = []
    for q in quartiles:
        row = [q] + [fmt_pct(matrix[q][t]) for t in types]
        rows.append(row)
    lines.append(md_table(headers, rows))
    lines.append("")
    # 간결 1줄
    lines.append(f"> 높은 누적 value (Q4) 콘텐츠의 **{dominant_pct:.1f}%가 {dominant_type}** "
                 f"· Q1 대비 +{diff:.1f}%p")
    lines.append("")
    return "\n".join(lines)


def render(results: dict) -> str:
    """Cross-tab 분석 섹션 — § 주요 인사이트 안의 깊이 분석 부분."""
    meta = results.get("_meta", {})
    key_metric_label = meta.get("key_metric_label", "행동")

    # 전체 type 분포 (편중 비교 baseline)
    ct = results.get("content_type", {}) or {}
    overall_type_share = {}
    for k, v in ct.items():
        if k.endswith("_pct") and isinstance(v, (int, float)):
            label = k.replace("_pct", "")
            overall_type_share[label] = float(v)

    parts = [
        _value_by_type_block(results.get("value_by_type", []), key_metric_label),
        _user_segments_block(results.get("user_segments", {}), key_metric_label),
        _top_content_type_dist_block(results.get("top_content_type_dist", {}), overall_type_share),
        _type_by_hour_block(results.get("type_by_hour", [])),
        _type_by_quartile_block(results.get("type_by_value_quartile", [])),
    ]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    return "\n".join(parts)
