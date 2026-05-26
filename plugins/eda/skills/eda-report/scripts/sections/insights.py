"""§인사이트 — 유저/콘텐츠/학습 관점별 grouping + 풍부한 multi-bullet.

3단 구조:
  ✅ 한 줄 결론 (suggestion or finding)
  - 비교 수치 부연 (3-4개)
  - 자동 생성 해석 (signal-aware)

Watcha EDA 스타일 — 인사이트를 관점별로 묶어서 비 ML 팀도 이해 가능.
"""
import re


# 분포 분석 (distributions.py) 에서 이미 다룬 signal — 중복 방지로 인사이트에서 제외
SIGNALS_COVERED_BY_DISTRIBUTIONS = {
    "temporal_peak",     # 시간대 분포
    "head_heavy",        # 콘텐츠 인기 (long-tail)
    "value_distribution", # Value 분포
}


# suggestion 텍스트 키워드 → finding.signal 매칭
SUGGESTION_TO_SIGNAL = [
    (re.compile(r"피크 시간대|peak.*hour|시청.*시간"), "temporal_peak"),
    (re.compile(r"평균 value|extreme.*value|시즌.*누적"), "extreme_value"),
    (re.compile(r"p99|활동량|봇|공유계정|bot"), "bot_suspect"),
    (re.compile(r"상위|pareto|long.?tail|head.?heavy|Gini"), "head_heavy"),
    (re.compile(r"sparsity|희소|cold.?start"), "sparsity"),
    (re.compile(r"MEH|싫어요|Gini.*큐레이터"), "meh_concentration"),
    (re.compile(r"부정 비율|hard.*negative"), "negative_pool"),
    (re.compile(r"재구매|repeat"), "repeat_pattern"),
    (re.compile(r"별점.*만점|평점.*신뢰"), "perfect_score"),
    (re.compile(r"cold.?start|1건만"), "cold_start"),
    (re.compile(r"value.*분포|value.*꼬리|value.*distribution"), "value_distribution"),
    (re.compile(r"품질|quality|null|중복|duplicate"), "quality_issue"),
]


# 알려진 RecSys 데이터셋 sparsity 비교 — sparsity 해석에 활용
KNOWN_SPARSITY = {
    "MovieLens-1M": 95.5, "MovieLens-25M": 99.46,
    "Netflix Prize": 98.82, "Amazon Reviews": 99.99,
    "Yelp": 99.87, "Gowalla": 99.99,
}


def _bullets_for(signal: str, ctx: dict, results: dict | None = None) -> list[str]:
    """signal + context (+ optional 전체 results) → 풍부한 부연 라인."""
    bullets = []
    results = results or {}
    overview = results.get("overview", {})

    if signal == "temporal_peak":
        peak_h = ctx.get("peak_hour")
        peak_c = ctx.get("peak_count", 0)
        avg = ctx.get("avg_daily")
        next_c = ctx.get("next_hour_count")
        n_total = overview.get("n_rows", 0)
        if next_c and peak_c:
            diff_pct = (peak_c - next_c) / next_c * 100
            bullets.append(f"다음 순위({next_c:,}건) 대비 **{diff_pct:+.1f}%** — top hour 강세")
        if avg and peak_c:
            ratio = peak_c / avg
            bullets.append(f"일평균({avg:,}건/일) 대비 시간당 **{ratio:.1f}배**")
        if n_total and peak_c:
            pct_total = peak_c / n_total * 100
            bullets.append(f"전체 인터랙션의 **{pct_total:.1f}%** 가 단일 시간대({peak_h}시)에 집중")
        # 점심/저녁 패턴 분석
        cs = results.get("case_studies", {})
        peak_hours = cs.get("peak_hours_top10", [])
        if peak_hours:
            top5_hours = [int(p["hour"]) for p in peak_hours[:5]]
            lunch = sum(1 for h in top5_hours if 11 <= h <= 15)
            evening = sum(1 for h in top5_hours if 18 <= h <= 22)
            if lunch >= 3:
                bullets.append(f"Top 5 시간대 중 **{lunch}개가 점심대(11~15시)** — 점심 휴식 소비 패턴")
            elif evening >= 3:
                bullets.append(f"Top 5 시간대 중 **{evening}개가 저녁대(18~22시)** — 일과 후 소비 패턴")

    elif signal == "extreme_value":
        n = ctx.get("n_extreme")
        top_val = ctx.get("top_value")
        top_key = ctx.get("top_content_key")
        n_contents = overview.get("n_contents", 0)
        if n and top_val and top_key:
            bullets.append(f"평균 value 3000+ 콘텐츠 **{n}개** — top: `{top_key}` ({top_val:.0f})")
        if n and n_contents:
            pct = n / n_contents * 100
            bullets.append(f"전체 콘텐츠의 **{pct:.2f}%** 에 불과하나 학습 loss 비대칭 영향")
        # value_describe 분포와 비교
        vd = results.get("value_describe", {})
        if vd:
            median = vd.get("median")
            std = vd.get("std")
            if median and top_val:
                ratio = top_val / median
                bullets.append(f"중앙값({median:.0f}) 대비 **{ratio:.0f}배** — 정상 시청 범위 벗어남")
            if std and top_val:
                z = (top_val - vd.get("mean", 0)) / std
                bullets.append(f"z-score **{z:.1f}** (mean={vd.get('mean', 0):.0f}, std={std:.0f}) — 통계적 outlier")

    elif signal == "bot_suspect":
        uid = ctx.get("user_id")
        n = ctx.get("n", 0)
        avg = ctx.get("avg", 0)
        ratio = ctx.get("ratio")
        n_users = overview.get("n_users", 0)
        if uid and n and avg:
            bullets.append(f"user `{uid}` 활동 **{n:,}건** (전체 평균 {avg:.0f}건 대비 **{ratio:.0f}배**)")
        if n_users:
            bullets.append(f"이 비율(전체 {n_users:,}명 중 1명)이 분포 꼬리에 위치 — 정상 분포와 단절")

    elif signal == "head_heavy":
        top1 = ctx.get("top1pct")
        top5 = ctx.get("top5pct")
        gini = ctx.get("gini")
        par = results.get("pareto_long_tail", {})
        top20 = par.get("top20pct")
        if top1 is not None and top5 is not None:
            bullets.append(f"상위 1% → 전체 **{top1:.1f}%** / 상위 5% → **{top5:.1f}%**")
        if top20:
            bullets.append(f"상위 20% → 전체 **{top20:.1f}%** — Pareto 80-20 룰 {'준수' if 75 <= top20 <= 85 else '벗어남'}")
        if gini:
            severity_label = "매우 강함" if gini > 0.8 else "강함" if gini > 0.6 else "보통"
            bullets.append(f"Gini **{gini:.3f}** — 콘텐츠 인기 불균등 {severity_label}")
        n_contents = overview.get("n_contents", 0)
        if n_contents and top1 is not None:
            n_top1 = int(n_contents * 0.01)
            bullets.append(f"콘텐츠 약 **{n_top1}개**가 인터랙션 1/6 차지 — 추천 다양성 위험")

    elif signal == "sparsity":
        s = ctx.get("sparsity_pct")
        avg_u = ctx.get("avg_per_user")
        n_users = overview.get("n_users")
        n_contents = overview.get("n_contents")
        if s:
            bullets.append(f"sparsity **{s:.3f}%** — 매트릭스 {100 - s:.4f}%만 채워짐")
        if avg_u and n_contents:
            coverage = avg_u / n_contents * 100
            bullets.append(f"유저당 평균 {avg_u:.1f}건 — 전체 콘텐츠({n_contents:,})의 **{coverage:.3f}%** 만 경험")
        # 비교
        if s:
            closer = min(KNOWN_SPARSITY.items(), key=lambda x: abs(x[1] - s))
            if abs(closer[1] - s) < 0.5:
                bullets.append(f"비교: **{closer[0]}** ({closer[1]:.2f}%) 와 유사한 sparsity 수준")
            elif s > 99.9:
                bullets.append(f"비교: Amazon Reviews(99.99%)/Gowalla(99.99%) 처럼 극도로 sparse")
            elif s < 99:
                bullets.append(f"비교: MovieLens-1M(95.5%) 수준의 비교적 dense 데이터")

    elif signal == "value_distribution":
        vd = ctx.get("value_describe") or results.get("value_describe", {})
        buckets = ctx.get("buckets") or results.get("value_buckets_pct", {})
        if vd:
            median = vd.get("median")
            mean = vd.get("mean")
            p95 = ctx.get("p95")
            if median and mean:
                skew = mean / median
                bullets.append(f"중앙값 {median:.0f} / 평균 {mean:.0f} — 우측 꼬리 **{skew:.2f}배** (skewed)")
            if p95 and median:
                ratio = p95 / median
                bullets.append(f"p95({p95:.0f}) / median 비율 **{ratio:.1f}배** — long-tail 분포")
        if buckets:
            top_bucket = max(buckets.items(), key=lambda x: x[1])
            bullets.append(f"가장 흔한 구간: **{top_bucket[0]}** ({top_bucket[1]:.1f}%)")

    elif signal == "quality_issue":
        ctx_quality = ctx.get("data_quality") or results.get("data_quality", {})
        notes = ctx_quality.get("notes", [])
        n_dup = ctx_quality.get("n_duplicates", 0)
        null_pct = ctx_quality.get("null_pct_by_column", {})
        if n_dup:
            bullets.append(f"중복 행 **{n_dup:,}건** 발견 — dedup 검토")
        elif n_dup == 0:
            bullets.append(f"중복 행 0건 — 무결성 OK")
        if null_pct:
            bad = [(k, v) for k, v in null_pct.items() if v > 1]
            if bad:
                bullets.append(f"null > 1% 컬럼: {', '.join(f'{k} ({v:.1f}%)' for k, v in bad)}")
        for n in notes[:2]:
            bullets.append(f"검출: {n}")

    return bullets


# 도메인 지식 + 비즈니스 함의 + 모델링 액션 3관점 해석.
# {signal: (비즈니스, 유저 행동, 모델링 권장)} 형식.
INTERPRETATION_3VIEW = {
    "temporal_peak": (
        "**비즈니스**: 점심대(11-15시) 집중은 모바일 / 짧은 시청 환경 시사 — 30분 이내 짧은 콘텐츠 또는 클립/하이라이트 콘텐츠 수급 가치.",
        "**유저 행동**: 직장인 점심 휴식 패턴 — 짧은 분량의 light viewing. 같은 유저가 저녁대에는 다른 패턴(긴 콘텐츠) 보일 가능성.",
        "**모델링**: time-of-day를 user/item embedding에 추가하거나, 시간대별 별도 reranker (점심대=짧은콘텐츠 우선, 저녁대=긴콘텐츠). Sequential model에 hour feature 통합.",
    ),
    "extreme_value": (
        "**비즈니스**: 평균 시청 시간이 비정상적으로 큰 콘텐츠 = 시리즈 시즌 누적 또는 long-form (다큐, 강의류). 인기 시리즈 후속 시즌 수급 ROI 확인 필요.",
        "**유저 행동**: 충성도 높은 유저들이 한 시리즈를 처음부터 끝까지 binge-watch하는 패턴. 일반 콘텐츠 1편 시청과 다른 행동 양상.",
        "**모델링**: 콘텐츠 단위를 에피소드로 분리 또는 value를 log-scale/quantile 정규화. Two-tower에서 popularity feature를 explicit binning. 시즌 누적 효과를 user side feature로 분리.",
    ),
    "head_heavy": (
        "**비즈니스**: 상위 5% 콘텐츠가 시청의 40% 점유 — 인기작 의존 매우 큼. 신작 노출 저조, long-tail 활용도 낮음. **다양성 메트릭 (Genre/Type entropy) 모니터링** + 신작 큐레이션 강화 검토.",
        "**유저 행동**: 검색·발견 단계에서 인기작에 끌리는 herd behavior. Cold-start 유저는 인기작 위주 추천받음 — diversity 부족 → churn 위험.",
        "**모델링**: in-batch negative를 inverse popularity 비율로 sampling (또는 mixed negative), popularity feature를 explicit (또는 debias) — popularity bias loss 함수 도입. Diversity reranker 추가.",
    ),
    "sparsity": (
        "**비즈니스**: 매트릭스가 매우 비어있음 — 유저가 전체 카탈로그의 극히 일부만 경험. **장기 retention 위해 콘텐츠 발견(discovery) UX** 강화 필요. 신규 가입 유저에게 어떤 콘텐츠를 보여줄지가 핵심.",
        "**유저 행동**: 대부분 유저가 검색·추천 의존. Browse 행동이 약함 → 추천 품질이 직접 retention에 영향.",
        "**모델링**: GNN/CF/Graph propagation 적합 (sparse한 user-item graph에서 잠재 표현 학습). Cold-start handling 필수 — content-based fallback (tag/genre/actor 기반) 추천 layer 추가. Side feature를 적극 활용.",
    ),
    "value_distribution": (
        "**비즈니스**: 시청 분포가 강한 우측 꼬리 — 일부 콘텐츠에서 binge-watch / 시즌 누적. 정상 1회 시청과 시리즈 완주가 같은 value 단위로 합쳐져 있음.",
        "**유저 행동**: 일반 시청은 짧음(median 501) but 일부 유저는 시리즈 deep-engagement (max 698K). 두 유형의 유저 행동을 같은 metric으로 측정하는 게 적절한지 재고.",
        "**모델링**: log-transform 또는 quantile binning으로 value 정규화. 또는 'normal viewing' vs 'deep engagement'로 분리해 multi-task로 학습.",
    ),
    "bot_suspect": (
        "**비즈니스**: 비정상적 활동량 유저 — 공유계정 / 자동화 봇 / 가족 단위 다중 사용 가능. 정상 1인 유저 행동과 분리해야 모델 품질 ↑.",
        "**유저 행동**: 한 계정에서 너무 많은 다양한 행동 — 한 사람의 취향이 아닐 가능성.",
        "**모델링**: 학습 전 outlier user filter (p99×10 cap) 또는 별도 그룹 (heavy user model 분리). Sample weight를 활동량 기반으로 down-weight.",
    ),
    "quality_issue": (
        "**비즈니스**: 데이터 품질 이슈 — null/중복/극단치 발견. 학습 결과가 noisy해질 위험. Source data pipeline 점검.",
        "**유저 행동**: 일부 비정상 값은 이벤트 로그 누락 또는 시스템 에러로 생성되었을 가능성 — 실제 유저 행동 아님.",
        "**모델링**: 학습 직전 sanity check (null %, outlier removal). Schema validation을 ETL 단계에 추가.",
    ),
    "meh_concentration": (
        "**비즈니스**: '싫어요' 신호가 소수 헤비 큐레이터에서 집중 — 일반 유저의 호불호 신호 부족. 명시적 부정 피드백 UX 강화 또는 implicit 부정 추론(quick-skip 등) 도입.",
        "**유저 행동**: 대부분 유저는 'meh' 안 누름 — silent dissatisfaction이 클 가능성. 시청 중단/짧은 시청을 implicit negative로 활용.",
        "**모델링**: explicit MEH 신호에 confidence weight 적용 (모두 동등 처리하면 소수 유저 취향에 over-fit). Implicit negative (skip, abandon)와 결합.",
    ),
    "negative_pool": (
        "**비즈니스**: 부정 비율 90%+ 콘텐츠 다수 — 콘텐츠 수급 품질 관리 필요. 평균 평점·시청 완주율 모니터링 강화.",
        "**유저 행동**: 일부 콘텐츠는 클릭하지만 만족 못 함 — Click ≠ Like. Title/thumbnail 어필력은 있지만 실제 만족도 낮음.",
        "**모델링**: 이런 콘텐츠를 hard negative pool로 학습 sampler에 우선 활용. 또는 모델이 click → satisfaction 분리 예측 학습 (multi-task).",
    ),
    "repeat_pattern": (
        "**비즈니스**: 동일 콘텐츠 재구매·재시청 — 강한 충성도. 시리즈 후속편 / 콜렉터블 콘텐츠 수급 전략 유효. 재구매 알림 UX 검토.",
        "**유저 행동**: 같은 콘텐츠를 반복 — 좋아하는 작품에 깊이 빠지는 유저 segment 존재.",
        "**모델링**: Recency feature 가치 큼. Sequential / Transformer 모델로 직전 행동 기반 다음 예측 강화.",
    ),
    "perfect_score": (
        "**비즈니스**: 평균 별점 만점 콘텐츠 다수 — 평가 표본 작아 신뢰도 낮을 가능성. 평점 가중치를 평가 수 기준으로 보정 (베이지안 추정).",
        "**유저 행동**: 광신 팬덤 영향 가능 — 일부 콘텐츠에 의도적 만점 부여.",
        "**모델링**: 평점 raw 값 대신 Bayesian average (m + Cm)/(n+C) 사용. 평가 수가 적으면 prior로 회귀.",
    ),
    "cold_start": (
        "**비즈니스**: 1회만 행동한 유저 비중 큼 — 신규 가입 유저 onboarding 핵심. 초기 추천 품질이 retention 결정.",
        "**유저 행동**: 가입 직후 한 번 보고 떠난 유저 또는 탐색 단계 유저. 충분한 history 없어 CF 어려움.",
        "**모델링**: Cold-start handling — content-based recommendation (tag/genre/popularity) 또는 hybrid 모델. Welcome flow에서 active preference elicitation.",
    ),
}


def _interpretation_for(signal: str) -> str:
    """signal 기반 3관점 해석 (비즈니스 / 유저 / 모델링).

    리턴값은 _render 단에서 prefix `- ` 가 붙으므로 첫 줄에 `- ` 없이 시작.
    여러 라인은 첫 줄에 raw 텍스트, 다음 줄들은 `- ` 자체 prefix.
    """
    views = INTERPRETATION_3VIEW.get(signal)
    if not views:
        return "_(해석: 이 패턴이 추천 모델/서비스에 갖는 의미)_"
    biz, user, model = views
    return f"{biz}\n- {user}\n- {model}"


def _match_signal(suggestion: str, findings: list[dict]) -> dict | None:
    """suggestion 텍스트 → 매칭 finding."""
    for pattern, signal in SUGGESTION_TO_SIGNAL:
        if pattern.search(suggestion):
            for f in findings:
                if f.get("signal") == signal:
                    return f
    return None


def _detect_signal_for_text(text: str) -> str | None:
    """suggestion 텍스트 → signal type (finding 없어도 추출)."""
    for pattern, signal in SUGGESTION_TO_SIGNAL:
        if pattern.search(text):
            return signal
    return None


def _render_finding_as_insight(f: dict, results: dict) -> list[str]:
    """Finding 1개 → 인사이트 한 블록 (multi-bullet + 해석)."""
    out = [f"✅ **[{f['signal']}] {f['value']}**"]
    for b in _bullets_for(f["signal"], f.get("context", {}), results):
        out.append(f"- {b}")
    if f.get("action_hint"):
        out.append(f"- _(권장: {f['action_hint']})_")
    out.append(f"- {_interpretation_for(f['signal'])}")
    out.append("")
    return out


def _render_suggestion_block(s: str, findings: list[dict], results: dict) -> list[str]:
    """Suggestion → 한 블록 (결론 + 부연 + 해석)."""
    out = [f"✅ **{s}**"]
    matched = _match_signal(s, findings)
    sig = matched["signal"] if matched else _detect_signal_for_text(s)
    ctx = matched.get("context", {}) if matched else {}
    for b in _bullets_for(sig or "unknown", ctx, results):
        out.append(f"- {b}")
    if sig:
        out.append(f"- {_interpretation_for(sig)}")
    else:
        out.append("- _(해석: 이 패턴이 추천 모델/서비스에 갖는 의미)_")
    out.append("")
    return out


def render(results: dict, inspect_report: dict | None = None,
           relevant_signals: set | None = None) -> str:
    """§인사이트 — 풀 모드는 관점별 grouping, Q&A는 단순 평탄."""
    sugs = results.get("analysis_suggestions", [])
    findings = (inspect_report or {}).get("findings", [])
    qa_mode = relevant_signals is not None

    # Q&A 모드 — 간결한 평탄 출력 (관점별 grouping 없음)
    if qa_mode:
        sugs = [s for s in sugs
                if (sig := _detect_signal_for_text(s)) is None or sig in relevant_signals]
        if not sugs:
            relevant_findings = [f for f in findings if f.get("signal") in relevant_signals]
            if not relevant_findings:
                return ""
            lines = ["## 💡 주요 인사이트", ""]
            for f in relevant_findings:
                lines.extend(_render_finding_as_insight(f, results))
            return "\n".join(lines)
        lines = ["## 💡 주요 인사이트", ""]
        for s in sugs:
            lines.extend(_render_suggestion_block(s, findings, results))
        return "\n".join(lines)

    # 풀 모드 — grouping 없이 단순 list. 분포 섹션과 중복인 signal 제외.
    if not sugs and not findings:
        return ""

    rendered_lines = []
    rendered_signals = set()

    # 1) suggestions 중 분포 섹션에서 안 다룬 것
    for s in sugs:
        m = _match_signal(s, findings)
        sig = m["signal"] if m else _detect_signal_for_text(s)
        if sig in SIGNALS_COVERED_BY_DISTRIBUTIONS:
            continue  # 분포 섹션에서 이미 다룸 — 중복 방지
        rendered_lines.extend(_render_suggestion_block(s, findings, results))
        if sig:
            rendered_signals.add(sig)

    # 2) suggestion에 없지만 strong/notable findings 중 분포에서 안 다룬 것
    for f in findings:
        sig = f.get("signal")
        if sig in rendered_signals or sig in SIGNALS_COVERED_BY_DISTRIBUTIONS:
            continue
        if f.get("severity") in ("strong", "notable"):
            rendered_lines.extend(_render_finding_as_insight(f, results))
            rendered_signals.add(sig)

    # 3) note severity (sparsity, quality 등 컨텍스트) — 분포 안 다룬 것만
    for f in findings:
        sig = f.get("signal")
        if sig in rendered_signals or sig in SIGNALS_COVERED_BY_DISTRIBUTIONS:
            continue
        if f.get("severity") == "note":
            rendered_lines.extend(_render_finding_as_insight(f, results))
            rendered_signals.add(sig)

    if not rendered_lines:
        return ""

    return "## 💡 추가 발견 및 권장\n\n" + "\n".join(rendered_lines)
