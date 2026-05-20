---
name: eda-casestudy
description: 보고서 Appendix에 들어갈 구체 사례를 추출한다 — 큰손 유저 TOP10, 충성 콘텐츠 TOP10, 헤비 rater 등. 도메인별 분기(mars/galaxy/adult/negative)로 적절한 case study 자동 선택. 또한 분석 도중 발견된 follow-up 제안을 analysis_suggestions에 누적. Use when EDA 끝나고 Appendix 케이스 추출이 필요할 때.
allowed-tools: Read, Write, Bash(python3 *), Bash(ls *)
argument-hint: <data_path> [--brief <brief.json>] [--out <analysis_results.json>] [--append] [--top-n 10]
disable-model-invocation: true
---

# EDA Case Study

## Overview

보고서 Appendix용 구체 사례 추출 스킬. "큰손 유저는 누구이고 얼마 썼는가", "충성도 높은 시리즈는 무엇인가" 같은 구체적 케이스를 TOP N 형태로 뽑아 `case_studies` 키에 저장한다. 도메인별로 자동 분기 (mars / galaxy / adult / negative).

또한 분석 도중 "더 보면 좋겠다"는 follow-up은 `analysis_suggestions` 키에 누적하여, 보고서 마지막의 "다음 분석 제안" 파트로 활용한다.

## Workflow

### Step 0: 입력 확인

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/run.py <data_path> \
    [--brief <brief.json>] \
    [--out ./analysis_results.json] \
    [--append] \
    [--top-n 10]
```

### Step 1: 도메인 분기

`data_path`에서 도메인 식별 → 4개 모듈 중 선택:

| 도메인 그룹 | 포함 경로 | 모듈 |
|---|---|---|
| **mars** | `graph_modeling/`, `next_watch/`, `next_purchase/`, `user_bert/` | `casestudies/mars.py` |
| **galaxy** | `rec_galaxy/`, `rating_prediction/` | `casestudies/galaxy.py` |
| **adult** | `rec_adult/` | `casestudies/adult.py` |
| **negative** | `graph_modeling/exp-*mehs*` (또는 negative 키워드) | `casestudies/negative.py` |

### Step 2: 도메인별 case study 실행

#### mars (시청·구매·BERT)
- 시청량 TOP N 유저 — value 합산 또는 행수 기준
- 다회차 시청 TOP N 콘텐츠 — value mean / max
- 시청 시간대 TOP N — 시간대 분포에서 극단치
- (메타 매핑) content → 제목 (`contents.pkl`)

#### galaxy / rating_prediction
- rating 최다 매김 TOP N 유저 — value_counts(user) 상위
- 평균 별점 TOP N 콘텐츠 — group by content, mean value
- 활발 reviewer — recency × frequency 조합

#### adult
- 큰손 TOP N — 총매출 (rental + possession 가격)
- 재구매 TOP N — 동일 content_id 반복 구매
- 헤비 buyer — 행수 + 매출 결합 score

#### negative
- MEH 헤비 TOP N — hard_neg_edges value=-1
- 저평점 헤비 TOP N — hard_neg_edges value 1~5
- 부정 비율 TOP N 콘텐츠 — neg / (neg + positive)

### Step 3: Follow-up 제안 자동 수집

각 case study 모듈은 분석 도중 발견된 흥미로운 패턴을 `suggest()` 함수로 별도 누적:

```python
# 예: mars.py
if heavy_user_value > p99 * 10:
    suggestions.append(
        f"유저 {user_id}는 활동량 p99의 10배 초과 — 봇/공유계정 의심, 별도 검증 권장"
    )
```

→ `analysis_suggestions` 리스트로 보고서 끝에 표시.

### Step 4: 출력 형식

```json
"case_studies": {
  "heavy_users_top10": [
    {"user_id": 7795744, "metric": "총 시청 누적", "value": 49, "extra": "다회차 시청 다수"},
    ...
  ],
  "loyal_content_top10": [
    {"content_id": 5803, "content_key": "1:2699", "title": "신과함께-죄와 벌",
     "metric": "평균 value", "value": 4521, "n_viewers": 308},
    ...
  ]
},
"analysis_suggestions": [
  "유저 7795744 활동량이 p99의 10배 — 봇/공유계정 의심",
  "특정 시리즈 (cid=1234) 평균 value 매우 높음 (>5000) — 학습 노이즈 가능"
]
```

### Step 5: 결과 보고

```
case_studies 추출 완료:
  - heavy_users_top10 (1번 유저: 49건 시청)
  - loyal_content_top10 (1번: 신과함께-죄와 벌)
  - active_raters_top10 (도메인이 rating일 때만)

analysis_suggestions 2개 누적
```

## 효율적 behavior_logs 활용

`behavior_logs/*.ftr` 같이 대용량 raw 로그를 다룰 때:

- **full scan 안 함** — `value_counts().head(N)` 같이 top N만 추출
- **메타데이터 lazy load** — content_id → 제목 매핑은 필요할 때만 `contents.pkl` 로드
- **chunked read** — 파일이 매우 크면 pandas chunksize 옵션 활용 (월별 또는 일별 sample)

## Resources

- **`scripts/run.py`**: 메인 진입점 (인자 파싱 + 도메인 분기)
- **`scripts/casestudies/__init__.py`**: casestudies 패키지 진입점
- **`scripts/casestudies/_common.py`**: 도메인 분기, top N 추출, 메타 매핑 helper
- **`scripts/casestudies/mars.py`**: mars 도메인 case study (시청·구매·BERT 통합)
- **`scripts/casestudies/galaxy.py`**: galaxy / rating_prediction case study
- **`scripts/casestudies/adult.py`**: 성인+ case study
- **`scripts/casestudies/negative.py`**: 부정 피드백 case study
- **`references/casestudy_catalog.md`**: 도메인별 case study 카탈로그 (어떤 사례를 추출하는지)
