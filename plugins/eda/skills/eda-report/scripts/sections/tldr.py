"""§핵심 요약 (TL;DR) — 풀 리포트 맨 앞.

3-5 bullet 자동 생성. 우선순위:
1. 데이터 스케일 (always)
2. 핵심 finding (strong → notable → note 순)
3. 시간/공간 분포 특징
4. 주요 suggestion
5. 데이터 기간/소스 (always)
"""
from ._common import fmt_compact, fmt_int, fmt_pct


def _scale_bullet(overview: dict) -> str | None:
    """데이터 규모 한 줄."""
    n_u = overview.get("n_users")
    n_c = overview.get("n_contents")
    n_r = overview.get("n_rows")
    if not (n_u and n_c and n_r):
        return None
    s = overview.get("sparsity_pct")
    sp = f", sparsity {s:.2f}%" if s is not None else ""
    return f"**{fmt_compact(n_u)} 유저** · **{fmt_compact(n_c)} 콘텐츠** · **{fmt_compact(n_r)} 인터랙션**{sp}"


def _temporal_bullet(results: dict) -> str | None:
    """시간 분포 특징 — 피크 시간대 vs 일평균 비율."""
    cs = results.get("case_studies", {})
    peak = (cs.get("peak_hours_top10") or [None])[0]
    dv = results.get("daily_volume", {})
    if peak and isinstance(dv, dict):
        counts = [v for v in dv.values() if isinstance(v, (int, float))]
        if counts and peak.get("n_actions"):
            avg_daily = sum(counts) / len(counts)
            ratio = peak["n_actions"] / avg_daily if avg_daily else 0
            return (f"시청 피크 **{peak['hour']}시** ({fmt_int(peak['n_actions'])}건) — "
                    f"일평균({fmt_int(int(avg_daily))}건) 대비 **{ratio:.1f}배**")
    return None


def _concentration_bullet(results: dict, gini: float | None) -> str | None:
    """집중도 한 줄."""
    par = results.get("pareto_long_tail", {})
    top5 = par.get("top5pct")
    if top5 is None:
        return None
    gini_part = f" (Gini **{gini:.3f}**)" if gini is not None else ""
    return f"콘텐츠 인기 매우 불균등 — 상위 5%가 전체의 **{top5:.1f}%** 점유{gini_part}"


def _suggestion_bullets(suggestions: list[str], max_n: int = 2) -> list[str]:
    """주요 suggestion (최대 N개)."""
    return [f"⚠ {s}" for s in suggestions[:max_n]]


def _period_bullet(meta: dict) -> str | None:
    """기간/데이터 소스."""
    s = meta.get("period_start")
    e = meta.get("period_end")
    n = meta.get("n_days")
    f = meta.get("main_file")
    if s and e:
        n_part = f" ({n}일)" if n else ""
        f_part = f" · `{f}`" if f else ""
        return f"기간 {s} ~ {e}{n_part}{f_part}"
    return None


def _get_gini(results: dict) -> float | None:
    """eda-overview/tail.py가 미리 계산한 gini 읽기 (single source of truth)."""
    return results.get("gini")


def render(results: dict, inspect_report: dict | None = None) -> str:
    """⚡ 핵심 요약 — 보고서 첫 인상. 데이터 규모 + 가장 강한 인사이트 4개.

    원칙: 데이터 통계는 아래 §데이터 개요와 중복되므로 1줄로만.
    나머지 3-4 bullets는 **의미 있는 인사이트** (단순 수치 X).
    """
    bullets = []
    overview = results.get("overview", {})
    gini = _get_gini(results)
    cross = {
        "value_by_type": results.get("value_by_type", []),
        "user_segments": results.get("user_segments", {}),
        "type_by_quartile": results.get("type_by_value_quartile", []),
    }

    # 1. 데이터 규모 한 줄 (간결)
    b = _scale_bullet(overview)
    if b:
        bullets.append(b)

    # 2. Cross-tab — 가장 큰 type 차이 (가장 강한 인사이트)
    vbt = cross.get("value_by_type", [])
    if len(vbt) >= 2:
        sorted_recs = sorted(vbt, key=lambda r: r.get("mean", 0), reverse=True)
        top, low = sorted_recs[0], sorted_recs[-1]
        if top.get("mean", 0) > 0 and low.get("mean", 0) > 0:
            ratio = top["mean"] / low["mean"]
            if ratio > 1.5:
                share = top.get("pct_of_total", 0)
                bullets.append(f"**{top['content_type']}** 1건당 평균 value가 "
                               f"**{low['content_type']}** 대비 **{ratio:.1f}배** — "
                               f"전체 value의 **{share:.1f}%** 점유")

    # 3. 집중도 (long-tail)
    b = _concentration_bullet(results, gini)
    if b:
        bullets.append(b)

    # 4. 시간 피크 (있고 의미 있을 때만)
    b = _temporal_bullet(results)
    if b:
        bullets.append(b)

    # 5. Cold-start segment 비중
    segs = cross.get("user_segments", {})
    if segs:
        light_pct = segs.get("pct", {}).get("Light (1-5건)", 0)
        if light_pct > 20:
            bullets.append(f"Light 유저 (cold-start) **{light_pct:.1f}%** — 비-CF 추천 필요")

    bullets = bullets[:5]
    if len(bullets) < 2:
        return ""

    lines = ["## ⚡ 핵심 요약", ""]
    for b in bullets:
        lines.append(f"- {b}")
    return "\n".join(lines) + "\n"
