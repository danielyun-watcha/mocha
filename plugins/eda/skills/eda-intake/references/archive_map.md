# Archive 도메인 매핑 사전

사용자가 자연어로 데이터를 언급할 때 어떤 `/archive` 경로로 매핑할지 가이드.

## 서비스 도메인 구조

Watcha의 데이터는 크게 **3개 독립 서비스 도메인**으로 나뉜다.

| 도메인 | 별칭 | 데이터 성격 |
|---|---|---|
| **mars** (왓차 본 서비스) | 왓차, 시청·구매, 본 서비스 | 영화/시리즈 시청·구매. galaxy와 데이터 독립 |
| **galaxy** (왓차피디아) | 피디아, 왓차피디아 | 평점/리뷰 + 멀티 타입 (Movie/TV/Webtoon/Book) |
| **성인관** | 성인+, adult | 성인+ 도메인. 렌탈·소장 중심 |

**중요 원칙**:
- mars와 galaxy는 **데이터를 독립적으로 사용**. 같은 콘텐츠라도 인덱서·메타가 다름
- 성인관은 별도 인덱서·메타
- 한 모델이 mars만 쓰거나, galaxy만 쓰거나, 성인관만 씀 (도메인 mixing 거의 없음)

## mars 도메인 (왓차 본 서비스)

| 자연어 키워드 | Archive 경로 | 핵심 파일 |
|---|---|---|
| 시청 / watch / 본 서비스 시청 | `/archive/next_watch/default/` | `watch_logs.ftr`, `train/`, `valid/`, `test/` |
| 구매 / purchase | `/archive/next_purchase/default/` | (시퀀스 학습용) |
| 다음 평점 (mars) / next rating | `/archive/next_rating/` | (현재 비어있을 수 있음) |
| 슬레이트 / slate | `/archive/next_slate/` | (개발 중) |
| **왓고리즘** / KG / 그래프 / LightKG / 설명가능한 추천 | `/archive/graph_modeling/builtin/` 또는 `exp-260406_daniel_lightkg/` | `train.ftr`, `kg_edges.pkl`, `content_tag_edges.pkl` |
| MEH / 싫어요 / 부정 피드백 (mars) | `/archive/graph_modeling/exp-260406_daniel_mehs/` | `hard_neg_edges.ftr` (저평점+MEH), `play_neg_edges.ftr` |
| User BERT / 행동 임베딩 (mars) | `/archive/user_bert/pretrain/` 또는 `behavior_logs/` | mars의 시청·구매 행동 BERT pretraining |

**참고**: `user_bert`는 mars의 시청·구매 데이터를 **내포한 사전학습** 결과. 즉 user_bert는 별개 도메인이 아니라 mars 데이터 활용.

## galaxy 도메인 (왓차피디아)

| 자연어 키워드 | Archive 경로 | 핵심 파일 |
|---|---|---|
| 평점 / 별점 / rating / 피디아 평점 | `/archive/rating_prediction/default/` | `ratings.ftr` (원본 245M행), `train.ftr` / `valid.ftr` / `test.ftr` |
| 피디아 / 왓차피디아 / galaxy / 멀티타입 | `/archive/rec_galaxy/builtin/` 또는 `/exp-260316_daniel_galaxy/` | `train.ftr` / `valid.ftr`, `contents.pkl`, `content_types.pkl` |

**galaxy 특징**: Movie/TV/Webtoon/Book 등 **멀티 타입**. 액션도 rate/wish/click/search 중심.

## 성인관 (성인+ 도메인)

| 자연어 키워드 | Archive 경로 | 핵심 파일 |
|---|---|---|
| 성인+ / 성인관 / adult / 렌탈 / 소장 | `/archive/rec_adult/builtin/` | `adults.ftr`, `CID_TO_*.pkl` (메타), `tags/`, `embeddings/` |
| 성인+ 다음 시퀀스 / next adult | `/archive/next_adult/exp-base/` | (시퀀스 학습용) |
| 성인+ User BERT | `/archive/user_bert_adult/pretrain/` 또는 `behavior_logs/` | 성인+ 행동 BERT pretraining |
| 성인+ Foundation | `/archive/adult_foundation/pretrain/` | 성인+ foundation model |
| Foundation (임시) | `/archive/foundation_tmp/` | foundation 실험 |

**성인관 특징**: 렌탈·소장이 핵심 전환. click/preview/play/wish/rental/possession 6종 행동.

## 개발 중 (데이터 미정)

| 자연어 키워드 | Archive 경로 | 상태 |
|---|---|---|
| 친구 / 팔로우 / follow | `/archive/rec_friend/` | **개발 중** — 데이터 미정 |
| 통합 추천 / unified | `/archive/unified_recommendation_/` | **개발 중** — 데이터 미정 |
| TVOD | `/archive/rec_tvod/` | 데이터 거의 없음 |

이 도메인이 매핑되면 사용자에게 "현재 개발 중이라 데이터가 미정입니다. 해당 위치에 있는 파일로 진행하시겠어요?" 라고 확인한다.

## 보조 모델 (보통 EDA 대상 아님)

| 키워드 | 경로 | 설명 |
|---|---|---|
| 듀얼 타워 / dual tower | `/archive/dual_tower/` | 듀얼 타워 모델 |
| MM 모델 / 멀티모달 | `/archive/mm_model/` 또는 `/archive/mmrec/` | 멀티 모달 추천 |
| 지식 그래프 (raw) | `/archive/knowledge_graph/` | KG 원천 (왓고리즘 prep 전) |
| 배우 인식 | `/archive/actor_recognition/` | 얼굴 인식 |
| 튜토리얼 | `/archive/tutorial/260316_daniel_tutorial/` | 학습용 |

## 외부 모델 (EDA 대상 절대 아님)

- `/archive/easyocr/`, `/archive/electra/`, `/archive/kogpt2/`, `/archive/monologg/`, `/archive/open_clip/`, `/archive/huggingface_cache/`

## 도메인 내부 표준 구조 — 전처리 vs 원본 로그

대부분의 도메인은 다음 패턴:

```
/archive/<도메인>/
├── builtin/ 또는 default/   # 전처리된 학습 데이터 (default prep)
├── exp-<exp_name>/          # 전처리된 학습 데이터 (실험별 prep)
├── behavior_logs/           # 원본 행동 로그 (raw, prep 전)
├── pretrain/                # pretraining 결과
├── embeddings/              # 임베딩 (rec_adult 등)
└── tags/, images/           # 메타 (rec_adult 등)
```

### 핵심 구분: "전처리 데이터" vs "원본 로그"

| 사용자 발화 키워드 | 의미 | 위치 |
|---|---|---|
| "전처리된", "학습 데이터", "prep 결과", "default", "builtin" | 학습용 prep 통과 데이터 | `builtin/` 또는 `default/` 또는 `exp-*/` |
| "실험 데이터", "최신 실험", 사용자명/날짜 명시 (예: "daniel 실험") | 특정 실험의 prep 결과 | `exp-<exp_name>/` |
| **"원본", "raw", "로그", "behavior log", "전처리 전"** | **원본 행동 로그** | **`behavior_logs/`** |

`behavior_logs/`가 있는 도메인:
- `/archive/graph_modeling/behavior_logs/` (Svod/, Tvod/ 서브디렉토리)
- `/archive/rec_galaxy/behavior_logs/` (날짜 범위 ftr 파일들)
- `/archive/rec_adult/behavior_logs/`
- `/archive/adult_foundation/behavior_logs/`
- `/archive/user_bert/behavior_logs/`
- `/archive/user_bert_adult/behavior_logs/`

**`exp-*` 우선순위**: 사용자가 "최신 실험" 또는 특정 실험명 언급 시 → `exp-<name>/`. 일반 "전처리 데이터"는 `builtin/` 또는 `default/`.

## 표준 학습 데이터 파일

| 파일 | 도메인 | 의미 |
|---|---|---|
| `train.ftr` / `valid.ftr` / `test.ftr` | 모든 도메인 | 학습/검증/테스트 분할 |
| `ratings.ftr` | rating_prediction | 원본 평점 (1~10) |
| `watch_logs.ftr` | next_watch | mars 시청 로그 |
| `adults.ftr` | rec_adult | 성인관 데이터 |
| `hard_neg_edges.ftr` | graph_modeling | 저평점 + MEH (mars 왓고리즘) |
| `play_neg_edges.ftr` | graph_modeling | 짧은시청 (mars 왓고리즘) |
| `extra_user_logs.ftr` | graph_modeling | 학습 직전 행동 로그 |
| `contents.pkl` | 모든 도메인 | 콘텐츠 인덱서 |
| `kg_edges.pkl` | graph_modeling | KG 엣지 |
| `content_tag_edges.pkl` | graph_modeling | 콘텐츠-태그 엣지 |
| `content_credit_edges.pkl` | graph_modeling | 콘텐츠-인물 엣지 |
| `CID_TO_*.pkl` | rec_adult | 성인+ 메타 매핑 |

## 매핑 워크플로

```
1. 키워드 매칭 시도 (위 표에서)
2. 후보가 1개면: 해당 경로의 builtin/default 또는 명시된 exp-* 선택
3. 후보가 여러 개면: 위 우선순위로 → AskUserQuestion으로 확인
4. 키워드 매칭 안 되면: /archive ls 후 ALL 후보 제시
5. 개발 중 도메인이면: 사용자에게 명시적으로 확인
```

### 매핑 예시

**전처리된 학습 데이터:**

| 사용자 발화 | 매핑 결과 |
|---|---|
| "평점 데이터" / "피디아 평점" | `/archive/rating_prediction/default/ratings.ftr` |
| "피디아 학습 데이터" / "galaxy" / "전처리된 피디아" | `/archive/rec_galaxy/builtin/train.ftr` |
| "최신 갤럭시 실험" | `/archive/rec_galaxy/exp-260316_daniel_galaxy/` |
| "성인관 데이터" / "성인+" | `/archive/rec_adult/builtin/adults.ftr` |
| "성인관 시퀀스" | `/archive/next_adult/exp-base/` |
| "왓고리즘" / "KG" / "설명가능한 추천" / "전처리된 graph_modeling" | `/archive/graph_modeling/builtin/` |
| "왓고리즘 부정 피드백" / "MEH" | `/archive/graph_modeling/exp-260406_daniel_mehs/` |
| "mars 시청" / "watch" | `/archive/next_watch/default/watch_logs.ftr` |
| "mars 구매" / "purchase" | `/archive/next_purchase/default/` |

**원본 행동 로그 (raw, behavior_logs):**

| 사용자 발화 | 매핑 결과 |
|---|---|
| "원본 로그" / "raw 데이터" / "전처리 전" (도메인 명시 必) | `/archive/<도메인>/behavior_logs/` |
| "피디아 raw" / "galaxy 행동 로그" | `/archive/rec_galaxy/behavior_logs/` |
| "성인관 raw" / "성인+ 행동 로그" | `/archive/rec_adult/behavior_logs/` |
| "왓고리즘 raw" / "graph_modeling 원본" | `/archive/graph_modeling/behavior_logs/` (Svod/, Tvod/ 서브) |
| "mars 원본 행동" | 도메인 확인 필요 — user_bert/behavior_logs/ 또는 graph_modeling/behavior_logs/ |

**기타:**

| 사용자 발화 | 매핑 결과 |
|---|---|
| "user_bert" / "행동 임베딩" | `/archive/user_bert/pretrain/` |
| "성인+ user_bert" | `/archive/user_bert_adult/pretrain/` |
| "친구 추천" / "팔로우" | `/archive/rec_friend/` + "개발 중 안내" |

## 모호한 경우 명확화 질문

사용자 발화가 모호하면 `AskUserQuestion`으로 확인:

| 모호한 발화 | 명확화 질문 |
|---|---|
| "시청 데이터" | "mars의 시청 로그인가요(next_watch), 아니면 mars 왓고리즘 학습 데이터인가요(graph_modeling)?" |
| "추천 데이터" | "어떤 도메인인가요? mars(시청·구매·왓고리즘) / galaxy(피디아) / 성인관" |
| "최신 실험" | "어떤 도메인 + 실험명을 알 수 있을까요?" |
| "behavior_logs" | "어떤 도메인의 원본 로그인가요? (mars=user_bert, 성인관=user_bert_adult, graph=rec_adult/behavior_logs)" |
| "데이터가 어디 있더라" | /archive ls 결과를 후보로 제시 |

## 자주 헷갈리는 케이스

1. **"시청 데이터"가 두 가지일 수 있음**:
   - mars 시청 시퀀스 학습 → `next_watch`
   - mars 왓고리즘 학습 (KG 기반) → `graph_modeling`
   - → "어떤 모델 학습용?"으로 확인

2. **"부정 피드백"은 거의 항상 mars 왓고리즘**:
   - `/archive/graph_modeling/exp-260406_daniel_mehs/`
   - (성인관에는 별도 부정 피드백 데이터셋 없음)

3. **"User BERT"는 도메인에 따라 다름**:
   - mars → `user_bert/`
   - 성인관 → `user_bert_adult/`

4. **`builtin` vs `default`는 거의 같은 의미**:
   - 도메인마다 명명만 다름. rec_adult/rec_galaxy/graph_modeling = `builtin/`, next_*/rating_prediction = `default/`

5. **`exp-*`는 사용자/날짜별 실험**:
   - 사용자가 "daniel 실험" 같이 말하면 `exp-*daniel*` 매칭
