# EDA Intake — Brief 예시

분석 brief는 EDA 흐름의 시작점이다. 아래 3개 예시는 실제 사내 EDA(성인+, rec_galaxy, 부정 피드백)에서 도출된 패턴이다.

## 예시 1: 일반적 도메인 EDA (성인+)

**사용자 대화 흐름:**

- Q: 어떤 데이터를 분석하시겠어요?
- A: `/archive/rec_adult/builtin`
- Q: 분석할 기간은?
- A: 전체 (자연 범위)
- Q: 분석 목적은?
- A: 도메인 유저 특성과 콘텐츠 선호 패턴을 파악해서 추천 모델 학습 방향을 잡고 싶음
- Q: 도메인 메모?
- A: 성인+ 도메인. 렌탈·소장 중심. 클릭·프리뷰·플레이·위시도 포함된 implicit feedback

**생성된 brief:**

```json
{
  "data_path": "/archive/rec_adult/builtin",
  "files": ["train.ftr", "valid.ftr", "test.ftr"],
  "period": {"start": "2025-08-01", "end": "2026-01-11", "days": 163},
  "goal": "도메인 유저·콘텐츠 선호 패턴 파악 + 추천 모델 학습 방향 도출",
  "focus_sections": ["overview", "action", "segment", "transition", "tail", "temporal", "taste"],
  "domain_notes": "성인+ 도메인. 렌탈·소장이 핵심 전환. 6종 행동(click/preview/play/rental/wish/possession).",
  "created_at": "2026-05-18T10:00:00Z"
}
```

## 예시 2: 멀티 타입 도메인 EDA (rec_galaxy)

**사용자 대화 흐름:**

- A: `/archive/rec_galaxy/30000`
- A: 79일 (sample_age 기준 전체)
- A: Movie/TV/Webtoon/Book 등 멀티 타입에서 타입별 행동 차이 + Strong/Weak 신호 분포 확인
- A: 30,000개 콘텐츠 유지 버전. 타입별 비중 차이가 매우 큼 (Movie 73% vs Webtoon 0.7%)

**생성된 brief:**

```json
{
  "data_path": "/archive/rec_galaxy/30000",
  "files": ["train.ftr", "valid.ftr"],
  "period": {"start": "2025-12-04", "end": "2026-02-22", "days": 79},
  "goal": "콘텐츠 타입별 행동 분포 차이 + Strong/Weak 신호 학습 가능성 검토",
  "focus_sections": ["overview", "action", "transition", "temporal"],
  "extra_sections": ["type_x_action_cross", "strong_ratio_label"],
  "domain_notes": "Movie/TV/Webtoon/Book 멀티 타입. Strong(rate/wish)와 Weak(click/search) 분리 학습 검토 중.",
  "created_at": "2026-05-18T10:30:00Z"
}
```

## 예시 3: 특정 신호 심층 EDA (부정 피드백)

**사용자 대화 흐름:**

- A: `/archive/graph_modeling/exp-260406_daniel_mehs`
- A: 학습 119일 + 직전 242일
- A: 세 부정 신호(MEH / 저평점 / 짧은시청)의 데이터 특성을 비교하고, 학습 시 어떻게 다뤄야 할지 근거 마련
- A: graph_modeling LightKG 학습 데이터. 부정 피드백 셋 분리 학습 셋업 검토 중

**생성된 brief:**

```json
{
  "data_path": "/archive/graph_modeling/exp-260406_daniel_mehs",
  "files": ["hard_neg_edges.ftr", "play_neg_edges.ftr", "train.ftr", "extra_user_logs.ftr"],
  "period": {"start": "2025-04-06", "end": "2026-04-05", "days": 365},
  "goal": "세 부정 신호의 데이터 특성 비교 + 학습 셋업 정당화",
  "focus_sections": ["overview", "segment", "tail"],
  "extra_sections": ["signal_overlap", "signal_lift_by_content", "user_signal_dominance"],
  "domain_notes": "부정 신호 3종(MEH/저평점/짧은시청). 학습 풀은 K-core 통과 144K 유저, 14K 콘텐츠.",
  "created_at": "2026-05-18T11:00:00Z"
}
```

## 패턴 요약

| 패턴 | 목적 유형 | focus_sections | 추가 섹션 |
|---|---|---|---|
| 도메인 일반 | "특성 파악" | 표준 7개 모두 | — |
| 멀티 타입 | "타입별 차이" | overview/action/transition/temporal | type_x_action_cross |
| 특정 신호 | "신호 비교/검증" | overview/segment/tail | signal_overlap, signal_lift |

## 사용자가 답을 잘 모를 때

흔한 경우:
- "그냥 데이터가 어떻게 생겼는지 보고 싶어요" → 도메인 일반 패턴 default
- "추천 모델이 잘 학습할 수 있을지 확인" → 도메인 일반 + segment + tail 강조
- "이 신호가 의미가 있는지 모르겠어요" → 특정 신호 패턴 + signal_overlap 추가

목적이 명확히 잡힐 때까지 한두 번 더 물어본다. 그래도 막연하면 도메인 일반 패턴으로 default.
