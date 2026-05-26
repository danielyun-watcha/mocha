# [실험명] A/B Test 사후 분석 보고서

> **사용 가이드**:
> - `<placeholder>` 채우고 불필요 섹션 삭제.
> - KPI 정의는 우리 abtest framework `remy/tasks/save/abtest/kpis/kpis.py` 기준.
> - mocha KPI endpoint 가 cover 하는 일반 KPI 는 직접 활용 (`/api/kpi/{domain}/summary`).

---

## 1. Experiment Setup

| 항목 | 값 |
|---|---|
| 실험명 | `<exp-name>` |
| 도메인 | `<galaxy / mars / adult>` |
| 가설 | `<예: 신규 추천 모델이 1인당 평가 수를 +5% 이상 증가시킨다>` |
| 실험 기간 | `<YYYY-MM-DD>` ~ `<YYYY-MM-DD>` (`<N>` 일) |
| Triggered 유저 | `<N>` 명 (rollout: `<%>`) |
| Control 그룹 | `<설명>` (n=`<N>`) |
| Treatment 그룹 | `<설명>` (n=`<N>`) |
| Pre-treatment 기간 | `<>` (실험 전 동질성 검증) |
| Primary KPI | `<예: 1인당 평가 수 (CTRPU)>` |
| Decision Threshold | `<예: p<0.05 & effect ≥ +3%>` |

---

## 2. KPI 셋 정의 (3 그룹)

### 2.1 DIFF 그룹 — 핵심 효과 측정

**Primary** (실험 가설 직접 검증):

| 지표 | 정의 | abtest framework 함수 |
|---|---|---|
| `<예: 1인당 재생 수>` | total plays / users | `action_count(PLAY, by_user=True).mean()` |
| `<예: 전체 CVR (click→play)>` | sum(PLAY)/sum(CLICK) | `click_through_rate()` 또는 derived |

**Secondary** (보조 측정):

| 지표 | 정의 |
|---|---|
| `<예: 1인당 평균 시청시간>` | sum(view_time) / users |
| `<예: 시청율 (binary)>` | users with play / total users |

### 2.2 GUARDRAIL 그룹 — 부작용 없는지 확인

| 지표 | 임계값 | 비고 |
|---|---|---|
| `<예: 1인당 클릭 수>` | -2% 이상 | 클릭 자체 감소 X |
| `<예: 1인당 보싶 수>` | -2% 이상 | 위시 활동 감소 X |
| `<예: CTR (전체 노출→클릭)>` | -1% 이상 | 노출 효율 유지 |
| `<예: 클릭율 (binary)>` | -1% 이상 | active user 비율 유지 |
| `<예: 재플레이율>` | -3% 이상 | retention 유지 |
| `<예: CVR (click→play)>` | -2% 이상 | 추천 정확도 유지 |
| `<예: 전체 click 대비 보싶 비율>` | -3% 이상 | 행동 균형 유지 |

### 2.3 DETERIORATION 그룹 — 악화 감지 시 즉시 롤백

| 지표 | 정의 | 롤백 임계값 |
|---|---|---|
| `<예: 1인당 재생 수>` | total plays / users | `<-5% 이상>` |
| `<예: 1인당 평균 시청시간>` | view_time / users | `<-5% 이상>` |
| `<예: 시청율 (binary)>` | users with play / total users | `<-3% 이상>` |

---

## 3. 동질성 검증 (Pre-treatment)

| 지표 | Control (pre) | Treatment (pre) | Δ | p-value |
|---|---:|---:|---:|---:|
| DAU | `<>` | `<>` | `<%>` | `<>` |
| 1인당 활동 | `<>` | `<>` | `<%>` | `<>` |
| `<>` | `<>` | `<>` | `<%>` | `<>` |

**결론**: 그룹 간 사전 차이 `<없음 / 있음>`. `<있음 → 보정 방법>`

---

## 4. Primary KPI 결과

### 4.1 `<Primary KPI 1>`

| 그룹 | n | 평균 | 표준편차 | 95% CI |
|---|---:|---:|---:|---|
| Control | `<>` | `<>` | `<>` | `<>` |
| Treatment | `<>` | `<>` | `<>` | `<>` |

- **상대 효과**: `<+X.X% (95% CI: +A% ~ +B%)>`
- **유의성**: p = `<>` (양측 검정)
- **판정**: `<유의 / 무의>` (decision threshold 기준)

### 4.2 일자별 추이 (`/api/kpi/.../series` 활용)

`<일자별 추이 차트 inline>` — Control vs Treatment 라인.

---

## 5. GUARDRAIL 결과

| 지표 | Control | Treatment | Δ | 임계값 통과 |
|---|---:|---:|---:|:---:|
| `<>` | `<>` | `<>` | `<%>` | ✓ / ✗ |

**결론**: 모든 guardrail `<통과 / X개 위반>`. `<위반 시 후속 액션>`

---

## 6. DETERIORATION 결과

| 지표 | Control | Treatment | Δ | 롤백 발동? |
|---|---:|---:|---:|:---:|
| `<>` | `<>` | `<>` | `<%>` | YES / NO |

---

## 7. Sub-segment 분석

특정 서브셋에서 효과가 다를 수 있음 (e.g. Cold Start vs Heavy User).

| Segment | Control n | Treatment n | Δ Primary | 비고 |
|---|---:|---:|---:|---|
| Cold Start (≤10) | `<>` | `<>` | `<%>` | `<>` |
| Heavy User (≥50) | `<>` | `<>` | `<%>` | `<>` |
| `<도메인별 segment>` | `<>` | `<>` | `<%>` | `<>` |

---

## 8. 부작용 / 이상치 점검

- 매출 영향 (adult 한정): `<+/- X% (₩Y)>`
- 특정 콘텐츠 타입 (Movie/TV/Webtoon) 별 차이: `<>`
- 데이터 이상치 / 측정 오류: `<없음 / 발견 시 보고>`

---

## 9. 결론 및 의사결정

### 9.1 Summary

`<3-5줄 핵심 요약 — Primary 통과 여부, guardrail 통과 여부, 의사결정>`

### 9.2 Decision

- **<출시 / 출시 안 함 / 추가 실험 / 롤백>**
- 근거:
  1. `<>`
  2. `<>`
  3. `<>`

### 9.3 Follow-up

| # | Action | Owner | Due |
|---|---|---|---|
| 1 | `<예: 새 모델 prod 배포>` | `<>` | `<YYYY-MM-DD>` |
| 2 | `<예: Cold Start segment 별도 실험>` | `<>` | `<>` |

---

## Appendix

### A.1 KPI 산식 (remy/tasks/save/abtest/kpis/kpis.py 기준)

| Code | 정의 |
|---|---|
| `action_count(X)` | count(action == X) |
| `CTR` | clicks / exposed_count |
| `CTRPU` | (clicks/exposed) per user → mean |
| `UCPU` | unique contents per user → mean |
| `active_users` | nunique(user) |
| `CVR` (TVOD) | (rental+possession) / click |
| `CRPU` (TVOD) | (purchase/click) per user → mean |
| `PUR` (TVOD) | (rental+possession) / active_users |
| `revenue` | sum(price) for rental+possession |
| `ARPU` | revenue / active_users |

### A.2 통계 방법

- 평균 비교: Welch's t-test (등분산 가정 X)
- 비율 비교: Z-test for proportions
- 다중 검정 보정: Bonferroni (필요 시)
- 효과 크기: Cohen's d / Lift %

### A.3 데이터 쿼리

```python
# Control / Treatment 그룹별 KPI 조회 (도메인 기준)
import requests
for grp, range_ in [("control", ...), ("treatment", ...)]:
    r = requests.get(f"http://localhost:8090/api/kpi/{domain}/summary",
                     params={"start": pre_start, "end": pre_end})
    # ... user_group filter 별도 필요 시 raw archive 직접 ...
```

> **주의**: mocha KPI endpoint 는 도메인 전체 사용자 집계. A/B 그룹 분리는 raw archive 의 `user_id` 필터링 또는 별도 abtest 파이프라인 (`remy/abtest/services/metric_calculators.py`) 활용.

### A.4 참고

- abtest framework: `remy/tasks/save/abtest/`
- 분석 자동화: `remy/abtest/services/metric_calculators.py`
- 과거 결과: Notion AB테스트 결과 모음 DB

---

*분석일: `<YYYY-MM-DD>` · 작성자: `<>` · Reviewers: `<>`*
