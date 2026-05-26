# Q&A 질문 라우팅

`render_qa.py`의 `QUESTION_ROUTES`가 키워드 정규식 → `case_study` 키로 매칭한다.

| 질문 키워드 | 매칭 case_studies |
|---|---|
| 큰손 / 헤비.*유저 / heavy.*user / 매출 / spender | `heavy_users_top10`, `heavy_spenders_top10` |
| 충성 / 다회차 / loyal / repeat | `loyal_content_top10`, `repeat_buyers_top10` |
| 피크 / 시간대 / peak.*hour | `peak_hours_top10` |
| 베스트 / bestseller / 많이.*팔 / 판매 | `bestseller_content_top10` |
| 별점 / rating / 평가.*많 / active.*rater | `active_raters_top10`, `highly_rated_content_top10` |
| 별점.*낮 / 최저.*평점 / disliked | `most_disliked_content_top10` |
| meh / 싫어요 / negative.*heavy | `meh_heavy_users_top10` |
| 부정.*비율 / neg.*ratio | `high_neg_ratio_content_top10` |
| 저평점 / low.*rating | `low_rating_heavy_users_top10` |

추가로 overview/temporal 트리거:

| 키워드 | 트리거 섹션 |
|---|---|
| 개요 / 얼마나 / 몇 명 / 규모 / sparsity / 희소 | `overview_section` |
| 시간 / 일별 / 월별 / 꼬리 / 롱테일 / lorenz / pareto / gini / 상위 | `temporal_tail` |

매칭 없으면 fallback 메시지 + 사용 가능한 case_study 키 목록 출력.

## 추가 패턴 가이드

새 case_study가 생기면:
1. `appendix.py`의 `CASE_TITLES`에 (제목, 헤더) 추가
2. `appendix.py`의 `_extract_row()`에 해당 키 분기 추가
3. `render_qa.py`의 `QUESTION_ROUTES`에 키워드 패턴 추가
