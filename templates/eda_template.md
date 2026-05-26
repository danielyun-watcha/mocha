# [도메인] EDA 보고서

> **사용 가이드**:
> - 모든 `<placeholder>` 채우고 불필요 섹션은 삭제.
> - KPI 값은 mocha KPI endpoint `GET /api/kpi/{domain}/summary?start=...&end=...` 로 즉시 조회 (Bash 정찰 불필요).
> - 도메인 ∈ {galaxy(피디아), mars(왓챠), adult(성인+)}.
> - 차트는 `/tmp/eda/*.png` 저장 후 `![](/eda-files/X.png)` 로 inline.

---

## Executive Summary

본 보고서는 **[도메인 한 줄 설명]** 의 탐색적 데이터 분석 결과를 담는다.
약 `<N>` 건의 사용자 상호작용 데이터를 분석한 결과, **[핵심 전략 한 줄]** 임을 확인.

### Key Findings

| 지표 | 수치 | 시사점 |
|---|---|---|
| `<핵심 지표 1>` | `<값>` | `<해석>` |
| `<핵심 지표 2>` | `<값>` | `<해석>` |
| `<핵심 지표 3>` | `<값>` | `<해석>` |

---

## 1. 데이터셋 개요

| 항목 | 값 |
|---|---|
| 데이터 기간 | `<YYYY-MM-DD>` ~ `<YYYY-MM-DD>` (`<N>`일) |
| 총 이벤트 | `<N>` 건 |
| DAU (unique users) | `<N>` 명 |
| Unique contents | `<N>` 개 |
| 1인당 평균 이벤트 | `<N>` 건 |

**데이터 소스**:
- `galaxy` → `/archive/rec_galaxy/behavior_logs/YYYYMMDD_YYYYMMDD.ftr`
- `mars`   → `/archive/user_bert/behavior_logs2/train/YYYYMMDD_YYYYMMDD.ftr`
- `adult`  → `/archive/rec_adult/behavior_logs/YYYYMMDD_YYYYMMDD.ftr`
- 평점 (galaxy/mars 공유): `/archive/rating_prediction/default/ratings.ftr`
- ADULT 가격: `/archive/rec_adult/builtin/CONTENT_TO_PRICE.pkl`

---

## 2. 행동 유형 분석

### 2.1 전체 행동 분포

| 행동 | 건수 | 비율 | 신호 강도 |
|---|---:|---:|---|
| `<action>` | `<N>` | `<%>`  | ○ Weak / ◐ Medium / ● Strong |

**도메인별 신호 정의**:
- **galaxy** (rec_galaxy): RATE/WISH = Strong, CLICK/SEARCH = Weak
- **mars** (user_bert): RATE/WISH/PLAY = Strong, CLICK/SEARCH = Weak
- **adult** (rec_adult): RENTAL/POSSESSION/WISH = Strong, CLICK/PREVIEW/PLAY = Weak

`Strong 신호 비율` 은 KPI endpoint 응답의 `kpis[]` 에서 직접 조회.

### 2.2 행동 전환 매트릭스 (Conversion)

| From → To | `<a1>` | `<a2>` | `<a3>` | ... |
|---|---:|---:|---:|---|
| `<a1>` | `<%>` | `<%>` | `<%>` | ... |

**핵심 전환률** (응답의 `kpis[]` `CVR click→...` 행 참고):
- `<from → to>`: `<%>` — `<해석>`

---

## 3. 사용자 세그먼트

### 3.1 활동량 세그먼트

| 세그먼트 | 정의 | 사용자 수 | 비율 | 평균 행동 수 |
|---|---|---:|---:|---:|
| Heavy User | `≥50` events | `<N>` | `<%>` | `<N>` |
| Medium | 10-49 events | `<N>` | `<%>` | `<N>` |
| Light / Cold Start | `≤10` events | `<N>` | `<%>` | `<N>` |

→ `Cold Start (≤10)` / `Heavy User (≥50)` 는 KPI endpoint 응답에서 직접.

### 3.2 도메인별 핵심 세그먼트

- **galaxy**: `평가자 (Rater)` vs `브라우저 (Browser)` — RATE 행동 유무로 구분
- **mars**: `시청자 (Player)` vs `검색 only` — PLAY 행동 유무
- **adult**: `구매자 (Buyer)` vs `비구매자` — RENTAL+POSSESSION 유무

---

## 4. 평점 분포 (galaxy / mars 한정)

`/archive/rating_prediction/default/ratings.ftr` 의 같은 기간 데이터.

| 평점 | 비율 | 시사점 |
|---|---:|---|
| ★1-3 | `<%>` | 부정 신호 |
| ★4-6 | `<%>` | 중립 |
| ★7-8 | `<%>` | 긍정 (피크 위치 확인) |
| ★9-10 | `<%>` | 강한 긍정 |

**평균 평점**: `<N>` / 10  (긍정 편향 여부 명시)

---

## 5. 콘텐츠 효율성

### 5.1 콘텐츠 타입 분포 (galaxy / mars)

| 타입 | 이벤트 | 비율 |
|---|---:|---:|
| Movie | `<N>` | `<%>` |
| TV | `<N>` | `<%>` |
| Webtoon | `<N>` | `<%>` |
| Book (galaxy) | `<N>` | `<%>` |

### 5.2 TOP 10 콘텐츠 / 장르 / 인기 인물

KPI endpoint 응답의 `top_contents` / `top_genres` / `top_directors` / `top_actors` 그대로 인용.

| 순위 | Content / Name | 이벤트 | 비고 |
|---:|---|---:|---|
| 1 | `<>` | `<>` | `<>` |

---

## 6. Long-tail / Pareto 분석

| 콘텐츠 상위 비율 | 이벤트 점유율 |
|---:|---:|
| 1% | `<%>` |
| 5% | `<%>` |
| 10% | `<%>` |
| 20% | `<%>` |

→ `Long-tail TOP 5%` KPI 값 인용.

**시사점**: 상위 `<X%>` 콘텐츠가 `<Y%>` 의 이벤트를 점유하는 long-tail 분포. Diversity 전략 필요 여부 판단.

---

## 7. 시간 패턴

### 7.1 시간대별 활동 (KST 0-23시)

KPI endpoint `hourly_activity` 응답.

- 피크 시간대: `<HH시>` (`<N>` events)
- 주말 vs 평일 (참고): `<>`

### 7.2 요일별 패턴 (선택)

`<요일별 분석>`

---

## 8. 희소성 (Sparsity) 분석

| 매트릭스 | 희소성 | 평가 |
|---|---:|---|
| 전체 상호작용 | `<%>` | `<dense / sparse>` |
| Strong 신호 only | `<%>` | `<>` |

→ KPI endpoint `희소성` 값 인용.

---

## 9. 비즈니스 특화 분석

### 9.1 매출 분석 (adult 한정)

- 기간 총매출: ₩`<N>`
- 1인당 매출 (구매자 기준): ₩`<N>`
- 일자별 매출 추이 (`revenue.daily_revenue`)
- TOP 매출 콘텐츠 (`top_revenue_contents`)
- rental vs possession 비중

### 9.2 재방문 / 재시청률

- 재방문율 (동일 user × content 2회+): `<%>`
- 재시청률 (mars PLAY 2회+): `<%>`
- 재구매율 (adult RENTAL 2회+): `<%>`

---

## 10. 핵심 인사이트 및 권장사항

### 10.1 데이터 강점 (Strengths)

| # | 강점 | 활용 방안 |
|---|---|---|
| 1 | `<예: 높은 재방문율>` | `<예: 시퀀스 기반 모델 학습>` |
| 2 | `<>` | `<>` |

### 10.2 데이터 도전과제 (Challenges)

| # | 도전과제 | 대응 전략 |
|---|---|---|
| 1 | `<예: Cold Start 비율 30%>` | `<예: 메타데이터 기반 초기 추천>` |
| 2 | `<>` | `<>` |

---

## 11. 결론

본 분석을 통해 다음 사용자 행동 특성을 확인:

1. **`<핵심 인사이트 1>`**: `<한 줄 설명>`
2. **`<핵심 인사이트 2>`**: `<한 줄 설명>`
3. **`<핵심 인사이트 3>`**: `<한 줄 설명>`

---

## Appendix

### A.1 분석 코드

```python
# KPI endpoint 호출 (Bash 정찰 대신)
import requests, json
domain = "galaxy"  # or "mars" / "adult"
r = requests.get(f"http://localhost:8090/api/kpi/{domain}/summary",
                 params={"start": "2026-05-17", "end": "2026-05-23"})
d = r.json()
for k in d["kpis"]: print(f"{k['label']:30} = {k['value']}")
```

### A.2 차트 디자인 룰

배경 흰색 / 강조 1색 (`#d97757`) + 나머지 회색 (`#D8D5CC`) / grid 없음 / 데이터 라벨 표시 / 200 DPI.

### A.3 데이터 가용 기간

`GET /api/kpi/domains` 응답의 `ranges` 참고.

---

*분석일: `<YYYY-MM-DD>` · 작성자: `<>`*
