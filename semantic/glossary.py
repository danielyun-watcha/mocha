"""Business Glossary — 사용자가 쓰는 일상 용어 ↔ 정규 지표(metric key).

PANDA 가 겪은 '맥락 부재로 비즈니스 로직 오해석'(예: "활성 매장" 기준 혼동) 을
구조적으로 막는 레이어.  애매한 용어의 기준(note)을 명시해 둔다.

resolve 흐름:  질문 → alias 매칭 → Term → metric key → Metric Registry 계약
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    canonical: str                 # 정규 명칭
    aliases_ko: tuple[str, ...]    # 사용자가 실제로 쓰는 표현(부분 문자열 매칭)
    maps_to: str                   # Metric Registry key
    definition_ko: str             # 기준(조회기준·모호성 해소에 사용)
    domains: tuple[str, ...]       # 적용 도메인
    note: str = ""                 # 모호성 해소 / 주의


_ALL = ("galaxy", "mars", "adult")
_GM = ("galaxy", "mars")
_AM = ("adult", "mars")

GLOSSARY: tuple[Term, ...] = (
    # 매출/구매
    Term("큰손", ("큰손", "큰 손", "vip", "헤비페이어", "헤비 페이어", "최다 결제", "최다결제", "결제왕"),
         "revenue.top_payers", "기간 내 결제액(렌탈+소장) 상위 유저", _AM),
    Term("매출", ("매출", "총매출", "총 매출", "수익", "거래액", "결제액"),
         "revenue.total", "기간 내 렌탈+소장 매출 합", _AM),
    Term("객단가", ("객단가", "arppu", "구매자당 매출", "인당 매출", "1인당 매출"),
         "revenue.arppu", "총 매출 ÷ 결제 유저 수", _AM),
    Term("결제유저", ("결제 유저", "결제유저", "구매자", "페잉유저", "유료 유저"),
         "revenue.paying_users", "기간 내 1건 이상 결제한 고유 유저", _AM),
    Term("전환율", ("전환율", "cvr", "결제 전환", "구매 전환"),
         "revenue.cvr", "결제 건수 ÷ 클릭 수", ("adult",)),
    Term("렌탈", ("렌탈", "대여"), "purchase.rental_total", "기간 내 렌탈(대여) 건수", ("adult",)),
    Term("소장", ("소장", "구매(소장)", "영구구매"), "purchase.possession_total", "기간 내 소장(영구구매) 건수", ("adult",)),

    # 인게이지먼트
    Term("활성유저", ("활성 유저", "활성유저", "액티브", "active", "mau", "dau"),
         "engagement.active_users", "선택 기간 내 1건 이상 액션한 고유 유저",
         _ALL, note="선택 기간 기준 — 고정 MAU/DAU 가 아니라 조회 기간 기준 활성"),
    Term("ucpu", ("ucpu", "유저당 콘텐츠", "소비 폭", "1인당 콘텐츠"),
         "engagement.ucpu", "활성 유저 1명이 소비한 고유 콘텐츠 평균 수", _ALL),
    Term("재생", ("재생", "플레이", "시청", "play", "본 횟수"),
         "engagement.play_total", "기간 내 PLAY(재생) 총합", ("mars",)),
    Term("평가수", ("평가 수", "평가수", "총 평가", "레이팅 수", "rate 수"),
         "engagement.rate_total", "기간 내 RATE(평가) 총합", _GM,
         note="'평점 분포'(별점 1~10 분포)는 rating.distribution 으로 분리"),
    Term("위시", ("위시", "보고싶어요", "보고 싶어요", "찜", "wish"),
         "engagement.wish_total", "기간 내 WISH 총합", _GM, note="wish 는 mars·galaxy 공유"),
    Term("클릭", ("클릭", "click", "조회수"),
         "engagement.click_total", "기간 내 CLICK 총합", _ALL),

    # 콘텐츠/장르/사람
    Term("인기장르", ("인기 장르", "인기장르", "장르 순위", "장르 top", "장르별"),
         "content.top_genres", "장르별 이벤트(소비) 순위", _GM,
         note="users 는 장르 단위 nunique(여러 장르 시청 유저 중복 카운트 X)"),
    Term("인기콘텐츠", ("인기 콘텐츠", "인기콘텐츠", "인기 작품", "많이 본", "많이본", "top 콘텐츠"),
         "content.top_contents", "콘텐츠별 이벤트(소비) 순위", _ALL),
    Term("고평점콘텐츠", ("평점 높은", "고평점", "별점 높은", "호평", "평점 top"),
         "content.top_rated", "평균 평점 상위 콘텐츠(최소 평가 수 필터)", _GM),
    Term("매출콘텐츠", ("매출 상위 콘텐츠", "돈 되는 콘텐츠", "매출 top 콘텐츠", "고매출"),
         "content.top_revenue", "콘텐츠별 매출 순위", _AM),
    Term("관심없어요", ("관심없어요", "관심 없어요", "meh", "별로에요", "별로예요", "싫어요", "부정 시그널"),
         "content.top_meh", "MEH(부정 시그널) 상위 콘텐츠", _GM,
         note="MEH 등록 시 동일 콘텐츠 WISH 자동 삭제(배타). 성인 콘텐츠 데이터 없음"),
    Term("인기배우", ("인기 배우", "인기배우", "배우 top", "배우 순위"),
         "people.top_actors", "소비 가중 인기 배우", _ALL),
    Term("인기감독", ("인기 감독", "인기감독", "감독 top", "감독 순위"),
         "people.top_directors", "소비 가중 인기 감독", _ALL),

    # 평점 분포
    Term("평점분포", ("평점 분포", "평점분포", "별점 분포", "별점분포", "평점 히스토그램"),
         "rating.distribution", "평점(1~10) 카운트 분포", _GM,
         note="behavior 와 별개 데이터셋(rating_prediction) — action_type 필터 무관"),

    # 유저/행동
    Term("헤비유저", ("헤비 유저", "헤비유저", "충성 유저", "활동 상위", "파워유저"),
         "users.top", "도메인 목적별 상위 유저(활동/결제)", _ALL),
    Term("시간대", ("시간대", "피크 타임", "피크타임", "언제 많이", "활동 시간"),
         "behavior.hourly", "0~23시 활동 분포(KST)", _ALL),
    Term("파레토", ("파레토", "집중도", "상위 유저 비중", "쏠림"),
         "behavior.pareto", "상위 유저 누적 이벤트 비중", _ALL),
    Term("추이", ("추이", "트렌드", "일별", "일자별", "변화"),
         "behavior.timeseries", "일자별 이벤트/유저 추이", _ALL),
)


__all__ = ["Term", "GLOSSARY"]
