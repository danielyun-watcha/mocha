"""Metric Registry — 비즈니스 지표의 '실행 가능한 계약(executable contract)'.

설계 핵심: `kpi.summary()` 가 이미 결정적으로 계산하는 ~20개 지표/블록에
비즈니스 의미(정의·식·tier·caveat·소스)를 입히는 메타 레이어다.  새 계산 X.

LLM 은 SQL/pandas 를 생성하는 대신 metric key 를 호출 → 같은 질문은 항상 같은
정의로 같은 숫자.  (PANDA 의 'text-to-SQL 매번 재생성 → 불일치/오해석' 을 구조적으로 제거)

resolve 규약:
  - "kpi:<라벨>"   → summary()["kpis"] 에서 label 일치 항목 (스칼라 KPI 카드)
  - "<dot.path>"   → summary() 결과의 중첩 경로 (예: revenue.revenue_per_paying_user)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MetricSpec:
    key: str                       # 정규 id (namespace.name)
    label_ko: str                  # 사람용 라벨
    definition_ko: str             # 1문장 비즈니스 정의 → 조회기준 문장에 재사용
    formula: str                   # 사람이 읽는 식
    resolve: str                   # summary() 결과 위치 ("kpi:라벨" | "dot.path")
    domains: tuple[str, ...]       # 적용 도메인 (galaxy/mars/adult)
    unit: str                      # KRW | count | ratio | star10 | per_user
    fmt: str                       # won | int | pct | f2 | star10  (값 포맷)
    tier: int                      # 4=SSOT검증 3=archive 2=derived 1=raw
    source_keys: tuple[str, ...]   # Source Registry 참조 키
    kind: str = "scalar"           # scalar | table  (table=top-N 리스트)
    dimensions: tuple[str, ...] = ()   # 분해 가능 축
    caveats: tuple[str, ...] = field(default_factory=tuple)


# 도메인 묶음 단축
_ALL = ("galaxy", "mars", "adult")
_GM = ("galaxy", "mars")
_AM = ("adult", "mars")

REGISTRY: tuple[MetricSpec, ...] = (
    # ── 인게이지먼트 (engagement) ────────────────────────────────────
    MetricSpec("engagement.active_users", "활성 유저 수",
        "선택 기간 내 1건 이상 액션한 고유 유저 수", "nunique(user_id)",
        "kpi:active_users", _ALL, "count", "int", 3,
        ("archive.behavior_logs",), dimensions=("date",),
        caveats=("선택 기간 기준 — MAU/DAU 와 다름", "KST 자정 경계")),
    MetricSpec("engagement.ucpu", "유저당 소비 콘텐츠(UCPU)",
        "활성 유저 1명이 소비한 고유 콘텐츠 평균 수", "nunique(content) / active_users",
        "kpi:UCPU", _ALL, "per_user", "f2", 3, ("archive.behavior_logs",)),
    MetricSpec("engagement.click_total", "총 클릭 수",
        "기간 내 CLICK 액션 총합", "sum(CLICK)",
        "kpi:총 CLICK", _ALL, "count", "int", 3, ("archive.behavior_logs",)),
    MetricSpec("engagement.click_per_user", "1인당 클릭",
        "활성 유저당 평균 CLICK 수", "sum(CLICK) / active_users",
        "kpi:1인당 CLICK", _ALL, "per_user", "f2", 3, ("archive.behavior_logs",)),
    MetricSpec("engagement.rate_total", "총 평가 수",
        "기간 내 RATE(평가) 액션 총합", "sum(RATE)",
        "kpi:총 RATE", _GM, "count", "int", 3, ("archive.behavior_logs",)),
    MetricSpec("engagement.rate_per_user", "1인당 평가",
        "활성 유저당 평균 RATE 수", "sum(RATE) / active_users",
        # NOTE: mars KPI 목록엔 '1인당 RATE' 가 없음(1인당 PLAY/WISH/CLICK만) → galaxy 전용.
        "kpi:1인당 RATE", ("galaxy",), "per_user", "f2", 3, ("archive.behavior_logs",)),
    MetricSpec("engagement.wish_total", "총 위시(보고싶어요)",
        "기간 내 WISH 액션 총합", "sum(WISH)",
        "kpi:총 WISH", _GM, "count", "int", 3, ("archive.behavior_logs",),
        caveats=("wish 는 mars·galaxy 공유 시그널",)),
    MetricSpec("engagement.play_total", "총 재생 수",
        "기간 내 PLAY(재생) 액션 총합", "sum(PLAY)",
        "kpi:총 PLAY", ("mars",), "count", "int", 3, ("archive.behavior_logs",)),
    MetricSpec("engagement.play_per_user", "1인당 재생",
        "활성 유저당 평균 PLAY 수", "sum(PLAY) / active_users",
        "kpi:1인당 PLAY", ("mars",), "per_user", "f2", 3, ("archive.behavior_logs",)),

    # ── 매출/구매 (revenue / purchase) ───────────────────────────────
    MetricSpec("revenue.total", "총 매출",
        "기간 내 렌탈+소장 매출 합", "sum(rental_price + possession_price)",
        "revenue.total_revenue", _AM, "KRW", "won", 3,
        ("archive.rec_adult.behavior_logs", "builtin.CONTENT_TO_PRICE"),
        caveats=("rental+possession 만 합산", "snapshot: 환불 미반영")),
    MetricSpec("revenue.paying_users", "결제 유저 수",
        "기간 내 1건 이상 결제(렌탈/소장)한 고유 유저", "nunique(user_id where purchase)",
        "revenue.paying_users", _AM, "count", "int", 3,
        ("archive.rec_adult.behavior_logs",)),
    MetricSpec("revenue.arppu", "구매자당 평균매출(ARPPU)",
        "총 매출 ÷ 결제 유저 수", "total_revenue / paying_users",
        "revenue.revenue_per_paying_user", _AM, "KRW", "won", 3,
        ("archive.rec_adult.behavior_logs",)),
    MetricSpec("revenue.top_payers", "최다 결제 유저(큰손)",
        "기간 내 결제액 상위 유저", "sum(price) by user, desc",
        "revenue.top_payers", _AM, "KRW", "won", 3,
        ("archive.rec_adult.behavior_logs",), kind="table"),
    MetricSpec("revenue.cvr", "결제 전환율(CVR)",
        "결제 건수 ÷ 클릭 수", "purchases / clicks",
        "kpi:CVR", ("adult",), "ratio", "pct", 3, ("archive.rec_adult.behavior_logs",)),
    MetricSpec("revenue.pur", "유저당 구매율(PUR)",
        "구매 건수 ÷ 활성 유저", "purchases / active_users",
        "kpi:PUR", ("adult",), "per_user", "f2", 3, ("archive.rec_adult.behavior_logs",)),
    MetricSpec("purchase.rental_total", "총 렌탈(대여)",
        "기간 내 RENTAL 액션 총합", "sum(RENTAL)",
        "kpi:총 RENTAL", ("adult",), "count", "int", 3, ("archive.rec_adult.behavior_logs",)),
    MetricSpec("purchase.possession_total", "총 소장(구매)",
        "기간 내 POSSESSION 액션 총합", "sum(POSSESSION)",
        "kpi:총 POSSESSION", ("adult",), "count", "int", 3, ("archive.rec_adult.behavior_logs",)),

    # ── 콘텐츠/장르/메타 (content / people) ──────────────────────────
    MetricSpec("content.top_genres", "인기 장르 TOP",
        "장르별 이벤트(소비) 순위", "events by genre, desc",
        "top_genres", _GM, "count", "int", 2, ("builtin.genre_map",), kind="table",
        dimensions=("genre",),
        caveats=("events 기준 순위", "users 는 장르 단위 nunique(중복 카운트 X)")),
    MetricSpec("content.top_contents", "인기 콘텐츠 TOP",
        "콘텐츠별 이벤트(소비) 순위", "events by content, desc",
        "top_contents", _ALL, "count", "int", 3, ("archive.behavior_logs",), kind="table"),
    MetricSpec("content.top_rated", "평점 높은 콘텐츠 TOP",
        "평균 평점 상위 콘텐츠 (최소 평가 수 필터)", "mean(rating) by content, desc",
        "top_rated_contents", _GM, "star10", "star10", 3,
        ("archive.rating_prediction",), kind="table"),
    MetricSpec("content.top_revenue", "매출 상위 콘텐츠",
        "콘텐츠별 매출 순위", "sum(price) by content, desc",
        "top_revenue_contents", _AM, "KRW", "won", 3,
        ("archive.rec_adult.behavior_logs", "builtin.CONTENT_TO_PRICE"), kind="table"),
    MetricSpec("content.top_meh", "관심없어요(MEH) 상위 콘텐츠",
        "MEH(관심없어요/별로에요) 부정 시그널 상위 콘텐츠", "count(MEH) by content, desc",
        "top_meh_contents", _GM, "count", "int", 3, ("archive.mocha.mehs",), kind="table",
        caveats=("MEH 등록 시 동일 콘텐츠 WISH 자동 삭제(배타)",
                 "AdultMovie/Webtoon 실데이터 없음")),
    MetricSpec("people.top_actors", "인기 배우 TOP",
        "소비 가중 인기 배우", "events-weighted actor rank",
        "top_actors", _ALL, "count", "int", 2, ("builtin.credit_edges",), kind="table"),
    MetricSpec("people.top_directors", "인기 감독 TOP",
        "소비 가중 인기 감독", "events-weighted director rank",
        "top_directors", _ALL, "count", "int", 2, ("builtin.credit_edges",), kind="table"),

    # ── 평점 분포 (rating) ───────────────────────────────────────────
    MetricSpec("rating.distribution", "평점 분포(1~10)",
        "기간·콘텐츠타입별 평점(1~10) 카운트 분포", "count by rating value",
        "rating_distribution", _GM, "count", "int", 3, ("archive.rating_prediction",),
        kind="table", dimensions=("content_type",),
        caveats=("⚠️ behavior 와 별개 데이터셋(rating_prediction) — action_type 필터 무관",
                 "평점은 1~10 정수(UI ★×2)", "KST 자정 경계")),

    # ── 유저/행동 분포 (users / behavior) ────────────────────────────
    MetricSpec("users.top", "활동·소비 상위 유저",
        "도메인 목적별 상위 유저 (galaxy/mars=활동, adult=결제)", "domain-specific top user",
        "top_users", _ALL, "count", "int", 3, ("archive.behavior_logs",), kind="table"),
    MetricSpec("behavior.hourly", "시간대별 활동",
        "0~23시 활동량 분포 (KST)", "events by hour(KST)",
        "hourly_activity", _ALL, "count", "int", 3, ("archive.behavior_logs",),
        kind="table", dimensions=("hour",), caveats=("KST 기준",)),
    MetricSpec("behavior.pareto", "유저 집중도(파레토)",
        "상위 유저가 차지하는 이벤트 누적 비중", "cumulative event share by user pct",
        "pareto_curve", _ALL, "ratio", "pct", 3, ("archive.behavior_logs",), kind="table"),
    MetricSpec("behavior.timeseries", "일자별 추이",
        "일자별 이벤트/유저 수 추이", "daily events & users",
        "timeseries", _ALL, "count", "int", 3, ("archive.behavior_logs",),
        kind="table", dimensions=("date",)),
    MetricSpec("behavior.actions", "액션 구성",
        "액션 타입별 건수 분포", "count by action_type",
        "actions", _ALL, "count", "int", 3, ("archive.behavior_logs",), kind="table"),
)


# key → spec 인덱스
BY_KEY: dict[str, MetricSpec] = {m.key: m for m in REGISTRY}


def metrics_for_domain(domain: str) -> list[MetricSpec]:
    """해당 도메인에서 사용 가능한 지표만."""
    return [m for m in REGISTRY if domain in m.domains]


__all__ = ["MetricSpec", "REGISTRY", "BY_KEY", "metrics_for_domain"]
