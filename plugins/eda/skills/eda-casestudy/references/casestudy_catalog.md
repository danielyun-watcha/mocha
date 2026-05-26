# Case Study 카탈로그

도메인별로 추출하는 case study 목록과 데이터 소스.

## 1. mars 도메인 (graph_modeling / next_watch / next_purchase / user_bert)

mars는 시청·구매·user BERT 모두 같은 데이터 (Watcha 본 서비스). 동일한 case study를 적용.

| Case study | metric | 데이터 소스 |
|---|---|---|
| **시청량 TOP N 유저** | 행수 또는 value 누적 | `train.ftr` user_id value_counts / groupby |
| **다회차 시청 TOP N 콘텐츠** | 평균 value (높을수록 다회차) | groupby(content) `value.mean()` |
| **시청 시간대 TOP N** | 시간대별 활동량 극단치 | `updated_at` → hour groupby |

## 2. galaxy / rating_prediction

| Case study | metric | 데이터 소스 |
|---|---|---|
| **rating 최다 TOP N 유저** | value_counts(user_id) | `ratings.ftr` 또는 `train.ftr` |
| **평균 별점 TOP N 콘텐츠** | groupby(content).value.mean() | (rating 데이터일 때만) |
| **활발 reviewer TOP N** | n_ratings × recency 조합 | timestamp 있을 때 |

## 3. adult (rec_adult)

| Case study | metric | 데이터 소스 |
|---|---|---|
| **큰손 TOP N** | 총매출 (rental_price × rentals + possession_price × possessions) | `adults.ftr` + `CID_TO_PRICE.pkl` |
| **재구매 TOP N 유저** | 동일 content_id 반복 구매 | groupby(user, content) |
| **헤비 buyer** | 행수 + 매출 결합 score | |

## 4. negative (graph_modeling/exp-*mehs)

| Case study | metric | 데이터 소스 |
|---|---|---|
| **MEH 헤비 TOP N 유저** | hard_neg_edges value=-1 count by user | `hard_neg_edges.ftr` |
| **저평점 헤비 TOP N 유저** | value 1~5 count by user | `hard_neg_edges.ftr` |
| **부정 비율 TOP N 콘텐츠** | (neg / (neg + positive)) by content | `hard_neg_edges.ftr` + `train.ftr` |

## 출력 row 표준 형식

```json
{
  "user_id": 7795744,        // 또는 "content_id"
  "content_key": "1:50814",  // content일 때
  "title": "해운대",          // (메타 매핑, lazy load)
  "metric": "총 시청 누적",   // 사람 읽는 metric 이름
  "value": 49,
  "extra": "추가 정보 (재구매 수, 평균 별점 등)"
}
```

## Analysis Suggestion 패턴

각 도메인 모듈에서 흥미로운 outlier가 발견되면 `suggest()`로 누적:

| 트리거 | 제안 메시지 예시 |
|---|---|
| 1명 유저 활동이 p99 × 10 초과 | "유저 {id}는 활동 p99의 10배 — 봇/공유계정 의심" |
| 콘텐츠 value 평균이 매우 큼 (>5000) | "콘텐츠 {id} 평균 value 5000+ — 학습 노이즈 가능" |
| 평균 별점 5.0인 콘텐츠 다수 | "평균 별점 5.0 콘텐츠 {N}개 — 평점 데이터 신뢰도 검증 필요" |
| 재구매율 30%+ 유저 | "재구매율 30%+ 유저 {N}명 — 충성 고객 특성 분석 가치" |

## 효율성 원칙

대용량 behavior_logs 처리 시:
1. **TOP N만** — `nlargest(N)` 또는 `value_counts().head(N)`
2. **메타 lazy load** — content/user 메타는 결과 정렬 후 N개만 매핑
3. **chunked read** — 단일 파일 1GB 초과 시 `pd.read_feather(use_threads=True)` 또는 chunk
