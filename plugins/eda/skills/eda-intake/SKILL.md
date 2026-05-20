---
name: eda-intake
description: EDA 시작 전 사용자에게 분석 데이터·기간·목적을 대화형으로 묻고 분석 brief를 생성한다. 자연어 도메인 키워드를 /archive 경로로 자동 매핑한다. Use when 사용자가 /eda를 호출했거나 EDA 분석을 시작하려 할 때, brief.json이 없는 상태에서.
allowed-tools: AskUserQuestion, Bash(ls *), Bash(find *), Bash(cat *), Bash(date *), Bash(python3 *), Read, Write
argument-hint: [domain_or_path_hint]
disable-model-invocation: true
---

# EDA Intake

## Overview

EDA 분석 시작 전 사용자에게 핵심 4가지를 묻고 `analysis_brief.json`을 생성한다. 사용자가 "평점 데이터", "피디아 도메인" 같이 자연어로 말하면 `/archive` 매핑 사전을 참조해 정확한 경로로 변환한다.

## Workflow

### Step 0: 인자 분석 + Archive 매핑

`$ARGUMENTS`가 있으면 먼저 `references/archive_map.md`를 참고해 자연어 키워드를 archive 경로로 매핑한다.

**매핑 우선순위:**

1. 절대 경로(/로 시작) → 그대로 사용
2. **"전처리" vs "원본 로그" 구분** (가장 중요):
   - 사용자가 "전처리된", "학습 데이터", "prep 결과" → `builtin/` `default/` `exp-*/` 후보
   - 사용자가 **"원본", "raw", "로그", "behavior log"** → **`behavior_logs/`** 후보
   - **명시 안 됨 → 전처리(builtin/exp-*) + 원본(behavior_logs) 후보를 모두 제시**. Step 1에서 사용자가 직접 선택. 이때 "전처리만 / 원본만 / 둘 다" 옵션도 같이 제공.
3. 도메인 키워드("평점", "피디아", "왓고리즘", "성인+" 등) → archive_map.md 매핑 표 참조
4. 키워드 매칭 안 되면 → `/archive` 디렉토리 ls 결과 보고 후보 추출

```bash
# 도메인 키워드인 경우 archive_map.md 표 참조
# 모호하면 /archive ls
ls /archive 2>/dev/null | head -30
```

자주 쓰는 매핑 (자세한 건 `references/archive_map.md`):

**galaxy (피디아):**

| 자연어 | 경로 |
|---|---|
| 평점/별점/rating | `/archive/rating_prediction/default/` |
| 피디아/galaxy/멀티타입 | `/archive/rec_galaxy/builtin/` |

**mars (왓차 본 서비스):**

| 자연어 | 경로 |
|---|---|
| 시청/watch | `/archive/next_watch/default/` |
| 구매/purchase | `/archive/next_purchase/default/` |
| 왓고리즘/KG/그래프/LightKG | `/archive/graph_modeling/builtin/` |
| MEH/부정 피드백 | `/archive/graph_modeling/exp-260406_daniel_mehs/` |
| user_bert (행동 임베딩) | `/archive/user_bert/pretrain/` |

**성인관:**

| 자연어 | 경로 |
|---|---|
| 성인+/성인관/렌탈/소장 | `/archive/rec_adult/builtin/` |
| 성인+ 시퀀스 | `/archive/next_adult/exp-base/` |
| 성인+ user_bert | `/archive/user_bert_adult/pretrain/` |

**원본 로그 (raw, behavior_logs):**

| 자연어 | 경로 |
|---|---|
| "원본"/"raw"/"전처리 전" + 도메인 | `/archive/<도메인>/behavior_logs/` |
| 피디아 raw / galaxy 행동 로그 | `/archive/rec_galaxy/behavior_logs/` |
| 성인관 raw / 성인+ 행동 로그 | `/archive/rec_adult/behavior_logs/` |
| 왓고리즘 raw / graph_modeling 원본 | `/archive/graph_modeling/behavior_logs/` |

**개발 중 (데이터 미정):**

| 자연어 | 경로 |
|---|---|
| 친구/팔로우 | `/archive/rec_friend/` |
| 통합 추천 | `/archive/unified_recommendation_/` |
| TVOD | `/archive/rec_tvod/` |

매핑이 모호하거나 후보가 여러 개면 (예: `builtin/` vs `exp-*/`) `AskUserQuestion`으로 확인한다.

### 서비스 도메인 3분류

Watcha 데이터는 **mars / galaxy / 성인관**의 3개 독립 도메인으로 나뉜다. 이 셋은 데이터가 독립적이라 인덱서·메타가 다르다.

- **mars** (왓차 본 서비스): 시청·구매·왓고리즘(KG)
- **galaxy** (왓차피디아): 평점·멀티타입 추천
- **성인관**: 성인+ 렌탈·소장

사용자 발화에서 어떤 도메인인지 먼저 식별. 예시:
- "시청" → mars (next_watch 또는 graph_modeling 중 선택)
- "평점" / "피디아" → galaxy
- "성인관" / "성인+" / "렌탈" → 성인관
- "왓고리즘" → mars 내부 (graph_modeling)
- "친구" / "통합 추천" → **개발 중** 안내 후 진행

### Step 1: 데이터 위치 확정

`probe_data.py`를 도메인 경로의 한 후보(예: `/archive/graph_modeling/builtin`)에 실행하면 결과의 `siblings` 필드에 같은 도메인의 다른 후보들이 카테고리별로 자동 분류되어 나온다:

```json
"siblings": {
  "preprocessed": [
    {"name": "builtin", "kind": "default", "path": "..."},
    {"name": "exp-260406_daniel_lightkg", "kind": "experiment", "path": "..."},
    {"name": "exp-260406_daniel_mehs", "kind": "experiment", "path": "..."}
  ],
  "raw": [{"name": "behavior_logs", "path": "..."}],
  "other": [{"name": "inference", "path": "..."}]
}
```

별도의 `ls` 호출 없이 이 결과를 그대로 AskUserQuestion 후보로 사용한다.

카테고리:
- **`preprocessed`**: 전처리 데이터 (`builtin/` `default/` `exp-*/`)
- **`raw`**: 원본 로그 (`behavior_logs/`)
- **`other`**: EDA 대상 아님 (`pretrain/` `embeddings/` `inference/` 등)

Step 0의 "전처리/원본/미언급" 분기에 따라 후보를 제시한다.

**미언급 (모두 후보) 케이스 — AskUserQuestion:**

```
질문: 어떤 데이터를 분석하시겠어요? (전처리 vs 원본 명시 안 되어 모든 후보 표시)

  ⓵ <도메인>/builtin/             ← 전처리: 기본 prep 결과
  ⓶ <도메인>/exp-<name1>/         ← 전처리: 실험 1
  ⓷ <도메인>/exp-<name2>/         ← 전처리: 실험 2
  ⓸ <도메인>/behavior_logs/       ← 원본 행동 로그 (raw)
  ⓹ 전처리 + 원본 모두 함께       ← 통합 EDA (양쪽 다 활용)
  ⓺ 직접 입력
```

**전처리 결정 케이스 — 전처리 후보만:**
```
  ⓵ <도메인>/builtin/
  ⓶ <도메인>/exp-<name1>/
  ⓷ <도메인>/exp-<name2>/
  ⓸ 직접 입력
```

**원본 결정 케이스 — behavior_logs만:**
```
  ⓵ <도메인>/behavior_logs/
```

후보가 1개면 바로 확정. 사용자 선택 후 `probe_data.py` 실행:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/probe_data.py <선택된_경로>
```

`${CLAUDE_SKILL_DIR}`는 이 스킬의 디렉토리(`SKILL.md`가 있는 곳)를 가리킨다. plugin·project·personal 어느 위치에 설치되었든 동일하게 동작한다.

probe 결과(파일 목록 + timestamp 범위)를 사용자에게 보여주고 분석 대상 파일이 맞는지 확인.

### Step 2: 분석 기간 확인

데이터 파일들이 서로 다른 기간을 가질 수 있다 (예: train.ftr 최근 4개월 + extra_user_logs.ftr 직전 8개월 + user_logs.ftr 더 옛날 raw). probe 결과의 **파일별 기간을 표로 보여주고** 어느 범위로 갈지 사용자가 선택하도록 한다.

표 형식 예시:
```
파일별 기간:
  train.ftr             2026-01-13 ~ 2026-05-12  (120일)
  valid.ftr             2026-01-13 ~ 2026-05-12  (120일)
  extra_user_logs.ftr   2025-05-13 ~ 2026-01-11  (243일, 직전 기간)
  user_logs.ftr         2024-11-23 ~ 2025-07-24  (raw, 더 옛날)
```

후보 기간을 `AskUserQuestion`으로 제시:
```
  ⓵ 학습 기간만 (train+valid 기간)
  ⓶ 학습 + 직전 기간 (extra 포함)
  ⓷ raw 전체 포함
  ⓸ 직접 지정 (YYYY-MM-DD ~ YYYY-MM-DD)
```

timestamp 컬럼이 없는 데이터(KG 메타 pkl 등)는 기간 추출 불가 — 사용자에게 명시적으로 묻는다.

### Step 3: 분석 목적 확인 (가장 중요)

이 단계가 가장 중요하다. 답이 막연하면 한두 번 더 구체화한다.

- 질문: "이 데이터를 분석하는 목적은 무엇인가요?"
- 예시 제시:
  - "도메인 유저 특성 + 콘텐츠 선호 패턴 파악"
  - "타입별 행동 차이 비교 (멀티 타입 도메인용)"
  - "특정 신호(예: 부정 피드백)의 특성 분석"
  - "A/B 테스트 가능 영역 발굴"

목적이 명확해지면 `focus_sections` 자동 결정:
- "도메인 일반" → 표준 7개 (overview/action/segment/transition/tail/temporal/taste)
- "타입별 차이" → overview/action/transition/temporal + `type_x_action_cross`
- "특정 신호" → overview/segment/tail + `signal_overlap`/`signal_lift`

자세한 매핑은 `references/intake_examples.md`.

### Step 4: 도메인 메모 (선택)

- 질문: "이 도메인에 대해 미리 알려주실 점이 있나요? (없으면 '없음')"
- 예시: "성인+ 도메인. 렌탈·소장 중심", "최근 신규 유저 유입 많음", "Movie 73% vs Webtoon 0.7%"

빈 답이면 생략한다.

### Step 5: Brief 확정 — Plan 형식 최종 확인

**EDA 수행 전 마지막 게이트**. 수집한 정보를 plan 형식으로 정리해 보여주고 사용자가 한 번에 검토할 수 있도록 한다. 이 단계가 누락되면 잘못된 가정으로 분석이 진행될 수 있다.

표시 형식 예시:

```
─────────────────────────────────────────────────────────────
 📋 EDA 분석 계획 (Plan)
─────────────────────────────────────────────────────────────
 도메인         mars (왓고리즘)
 데이터 종류     전처리된 학습 데이터
 데이터 경로    /archive/graph_modeling/builtin/
 분석 파일       train.ftr, valid.ftr, kg_edges.pkl, ...

 기간           2026-01-13 ~ 2026-05-12 (120일, 학습 기간만)

 분석 목적       왓고리즘 학습용 도메인 특성 + 추천 모델 학습 사전 검토

 수행할 섹션
   ✓ overview      — 기본 통계 (행 수, 유저, 콘텐츠)
   ✓ action        — 행동 유형 분포 + 학습 타겟
   ✓ segment       — 유저 세그먼트 (Heavy/Light, Cold-start)
   ✓ tail          — Pareto / Long-tail
   ✓ temporal      — 시간 패턴 (요일/시간/월)
   ✓ taste         — Light vs Heavy 메타 다양성
   + signal_coverage  — KG 메타 × 행동 교차 (추가)

 도메인 메모     mars 왓고리즘 LightKG. KG 메타와 행동 결합. positive 위주.
─────────────────────────────────────────────────────────────
```

`AskUserQuestion`으로 확정:
- 질문: "이 plan으로 EDA를 진행할까요?"
- 선택지:
  - "✅ 진행하기"
  - "✏️ 수정 필요 (어디?)"

"수정 필요" 선택 시 어느 항목(데이터/기간/목적/섹션/도메인 메모)을 수정할지 다시 묻는다.

확정되면 `analysis_brief.json` 저장. 저장 경로:
- 사용자가 cwd에서 작업 중이면 `./eda_brief.json`
- 분석 결과 저장 디렉토리가 명시되면 거기

```json
{
  "data_path": "/archive/.../",
  "files": ["train.ftr", "..."],
  "period": {"start": "2026-01-01", "end": "2026-04-30", "days": 119},
  "goal": "구체화된 목적 한 줄",
  "focus_sections": ["overview", "action", "segment", "transition", "tail", "temporal", "taste"],
  "extra_sections": [],
  "domain_notes": "도메인 메모 (있으면)",
  "created_at": "ISO8601 timestamp"
}
```

### Step 6: 다음 단계 안내

저장 완료 후 `AskUserQuestion`으로 다음 단계 묻기:
- 질문: "이어서 EDA 분석을 진행할까요?"
- 선택지: "분석 시작 (/eda)", "나중에"

"분석 시작" 선택 시 `eda` 오케스트레이터 호출. `brief.json` 경로를 인자로 전달.

## 사용자가 답을 모를 때

흔한 경우와 대응:

| 사용자 발화 | 대응 |
|---|---|
| "데이터가 어디 있더라" | `/archive` ls 결과 보여주고 도메인 후보 제시 |
| "그냥 데이터 어떻게 생겼는지 보고 싶어요" | 도메인 일반 패턴 default + 표준 7개 섹션 |
| "추천 모델 학습 잘 될지 확인" | 도메인 일반 + segment/tail 강조 |
| "이 신호가 의미 있는지 모르겠어요" | 특정 신호 패턴 + signal_overlap 추가 |
| "잘 모르겠다 / 추천해줘" | 도메인 메모 묻고 다시 시도. 그래도 막연 → 도메인 일반 default |

## Resources

- **references/archive_map.md**: 자연어 키워드 → /archive 경로 매핑 사전 (전체)
- **references/intake_examples.md**: brief 예시 3종 (rec_galaxy / 성인+ / 부정 피드백) + 답 모를 때 가이드
- **scripts/probe_data.py**: 데이터 경로에서 파일 목록 + timestamp 범위 자동 추출
