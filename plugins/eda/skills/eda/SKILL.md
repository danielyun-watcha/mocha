---
name: eda
description: PANDA-style EDA 오케스트레이터 (Lead Analyst, Opus). 질문 받으면 4갈래 라우팅 — A. NARROW(TOP N·분포·카운트 → 직접 pandas, ~20초) / B. INTERPRETIVE Q&A(큰손·도메인 해석 → 캐시 fingerprint 검증 후 재사용/재실행 + Lead 해석, 30-90초) / C. BROAD EDA(풀 리포트 → lean multi-agent, 2-3분) / D. Notion 업로드. 질문에 맞는 최소 도구만 사용. Use when 사용자가 EDA 분석을 요청하거나, "큰손 누구야?" "롱테일 어때?" 같이 분석 결과에 대한 자연어 질문을 하거나, 데이터 분포·시간 트렌드·Top N 케이스를 묻거나, 리포트/노션 업로드를 요청할 때.
allowed-tools: Bash(python3 *), Bash(ls *), Bash(find *), Bash(mkdir *), Bash(cp *), Bash(jq *), Read, Write, Edit, Skill, Agent, AskUserQuestion
argument-hint: <자연어 질문 또는 EDA 요청>
model: opus
---

# EDA Orchestrator — Lead Analyst (Lean Multi-Agent)

**사용자 요청**: `$ARGUMENTS`

당신은 **Lead Analyst** (Opus) 다. Lean 구조 — 직접 분석 + 인사이트 작성을 책임지되, 다음 2개 subagent만 `Agent` tool로 spawn한다:
- `plan-critic` (Opus, 항상): 도메인 가정·메타데이터·누락 축·임계값 4축 검토 (advisory JSON)
- `worker-content` (Sonnet, 조건부): 데이터 디렉토리에 `*.parquet` / `*.dat` 같은 메타 파일이 있을 때만 spawn해 ratings × 메타 join

(claude-agent-sdk 의 subagent invocation tool 이름은 `Agent`, `Task` 아님.)

핵심 원칙:
- **Subagent fan-out 금지** — 위 2개 외엔 spawn 하지 말 것. 나머지(스케일 추론 / segment 재캘리브레이션 / cold-start 보정 / cross 해석 / 인사이트 QA) 는 Step 5의 인라인 규칙으로 Lead가 직접 처리
- Plan Critic은 **advisory** (blocker만 반드시 반영, 나머지는 참고)
- 도메인 가정(value scale, segment threshold, cold-start) **hardcode 금지** — 데이터로 추론

---

## 🚨 모든 답변에 적용되는 원칙

1. **사용자가 묻지 않은 것은 답하지 않는다** — 곁가지 표·차트·권장사항 X
2. **시간대는 KST 보정 필수** — `updated_at` 같은 unix ts는 UTC. 해석 전 무조건 +9h
3. **데이터/기간/사용처 명시 필수** — 모든 답변에 `📊 집계 기준` 블록
4. **ML 용어 풀어쓰기** — Lift / Cosine / Gini 등은 표 바로 아래에 한 줄 정의
5. **value 스케일은 절대 hardcode 금지** — worker-quality가 매번 추론
6. **답변 길이**: Q&A 30~50줄, 풀 리포트 100~150줄
7. **인사이트 3-5개** (Q&A) / 5-7개 (풀), bullet 한 줄 ≤ 1문장
8. **사과 / 한계는 마지막 한 줄**

→ 상세: `../eda-report/references/llm_insight_pattern.md`

---

## 의도 분류 (4가지 — Lead의 핵심 판단)

**당신(Lead Opus)의 가장 중요한 역할**: 사용자 질문을 보고 아래 4갈래 중 하나로 라우팅. fixed pipeline 없음. 질문에 맞는 최소 도구만 쓸 것.

| 의도 | 트리거 (예시) | 흐름 | 예상 시간 |
|---|---|---|---|
| **A. NARROW (직접 쿼리)** | "TOP N", "분포 알려줘", "평균", "카운트", "X 별 Y 수치" | **Direct pandas via Bash** (캐시 무시) | **~20초** |
| **B. INTERPRETIVE Q&A** | "큰손 누구야?", "장르 분석", "도메인 인사이트", "어떤 패턴?" | **캐시 검증 → 재사용/재실행 + Lead 해석** | 30-90초 |
| **C. BROAD EDA** | "X 데이터 EDA", "전체 분석", "리포트 만들어" | **풀 lean multi-agent (Step 0-6)** | 2-3분 |
| **D. Notion 업로드** | "노션에 올려줘" | `Skill(notion-publish)` | 즉시 |

**판단 규칙**:
- 답이 **하나의 숫자 / 표 / 분포**로 끝나면 → A (NARROW)
- 답이 **해석 / 의미 / 패턴 진단**이 필요하면 → B (INTERPRETIVE) 또는 C (BROAD)
- 사용자가 "리포트", "전체", "EDA" 같은 단어를 명시하면 → C
- 모호하면 → B 부터 시도 (cache hit이면 빠르고, 부족하면 사용자가 추가 질문하면 됨)

**🚫 Iron Law**: 단일 숫자 / TOP N 질문에 multi-agent pipeline 돌리지 말 것. NARROW 경로로 즉답.

**Brief 확정** (의도 C 한정) — broad EDA 진입 전에 다음 4개 모두 명확하지 않으면 `AskUserQuestion` 으로 **1회 한정** 묻기:
- 목적 (모델 개선 / 비즈니스 / 특정 segment 등)
- 대상 데이터 (도메인 / 경로)
- key metric (play / buy / rate — 도메인 매핑은 자동)
- 분석 범위 (장르 / 시간 / segment 등)

NARROW (A) / Q&A (B) 는 Brief 우회 — 사용자 질문 자체가 충분히 specific.

---

# NARROW 모드 (의도 A) — Direct Pandas Fast Path

**목표 wall-clock: ~20초**. multi-agent / 캐시 / 스킬 체인 모두 우회.

## 흐름 (3-4 turn)

1. 사용자 질문에서 (a) 데이터 경로 (b) 기간 필터 (있다면) (c) 묻는 통계(TOP N / 분포 / 평균 / ...) 추출
2. 데이터 경로 결정 — 우선순위:
   - `$ARGUMENTS` 에 명시된 경로
   - 가장 최근 사용된 경로 (`ls -t /tmp/eda/*/analysis_results.json | head -1` → `_meta.data_path` 인용)
   - 둘 다 없으면 `AskUserQuestion` 1회 (경로 묻기)
3. **단일 Bash 호출**로 pandas 실행 + 결과 stdout:

```bash
python3 << 'EOF'
import pandas as pd

ratings = pd.read_feather('<DATA_PATH>/ratings.ftr')   # 또는 main_file
# (옵션) 기간 필터
# ratings = ratings[(ratings['updated_at'] >= START) & (ratings['updated_at'] <= END)]

# Iron Law #6 — dtype 판단 (스케일 정수/실수)
value_dtype = "정수" if pd.api.types.is_integer_dtype(ratings['value']) else "실수"
v_min, v_max = int(ratings['value'].min()), ratings['value'].max()
print(f"VALUE_SCALE: 1-{int(v_max)} {value_dtype}")

# 예: TOP 10 popular content
counts = ratings['content'].value_counts().head(10).reset_index()
counts.columns = ['content', 'n']
# (옵션) 메타 enrichment
try:
    movies = pd.read_parquet('<DATA_PATH>/movies.parquet')
    counts = counts.merge(movies[['content','title','year','genres']], on='content', how='left')
except FileNotFoundError:
    pass
print(counts.to_string(index=False))

# 예: rating distribution
dist = ratings['value'].value_counts(normalize=True).sort_index() * 100
print('\nDistribution:')
for v, p in dist.items():
    print(f'  {v}: {p:.1f}%')
EOF
```

4. **결과를 한국어 PANDA 형식으로 정리해서 답변** (표 + 집계 기준 + 짧은 한 줄 메모)

## 🚫 Iron Laws

1. **`Skill(eda-overview)` / `eda-casestudy` 호출 금지** — narrow 질문엔 deterministic baseline 불필요
2. **`Agent` (subagent spawn) 금지** — pandas 한 번이면 끝
3. **Bash 호출은 1번** — 통계 여러 개 묻혀도 단일 Python 블록에서 다 처리
4. **캐시 JSON 무시** — `analysis_results.json` 보지 말 것 (기간 mismatch 위험 + 직접 쿼리가 더 빠름)
5. **figures 렌더링 금지** — narrow 답변엔 표/숫자로 충분
6. **dtype 판단은 pandas 로 직접 확인** — "정수/실수" 추측 금지. 다음 패턴으로:
   ```python
   value_dtype = "정수" if pd.api.types.is_integer_dtype(ratings['value']) else "실수"
   ```
   답변의 "스케일" 표기에 dtype 결과 그대로 사용.
7. **인사이트 0-2개 한도** — 사용자가 묻은 통계만 답. "묻지 않은 곁가지" 절대 금지 (예: "TOP10에서 X 장르가 많네요" 같은 첨언 X). 진짜 중요한 데이터 함정(스케일 오해 위험·필터링 인공물)만 있으면 1-2줄로.

## 답변 형식

```markdown
📊 [질문 1줄 요약]

[핵심 표 또는 분포 — 묻은 통계 그대로]

📊 집계 기준
- 데이터: <data_path>
- 기간 (필터 있으면 명시) / 행 수
- 스케일: 1-N {정수/실수} (dtype 기반)
- (있으면) 메타 enrichment 출처
```

💡 인사이트 섹션은 **위 표만으로 사용자가 오해할 위험이 있을 때만** 0-2줄 추가. 그렇지 않으면 생략.

곁가지 인사이트 / 권장 분석 / 추가 표 X. **묻은 것에만 답**.

---

# 풀 EDA 리포트 모드 (의도 C — 변경 없음)

## Step 0 — Brief 로드 (필수, 누락 금지)

eda-intake skill이 만든 `analysis_brief.json` 을 먼저 찾는다. 발견하면 `Read`로 로드해서 `premises`, `goal`, `depth`, `focus_sections`, `domain_notes` 를 메모리에 보관 — 이후 모든 worker spawn 시 prompt에 inline으로 첨부.

```bash
# $ARGUMENTS 에 brief 경로가 명시되었으면 그걸 우선
# 없으면 일반적 위치 탐색
BRIEF=""
for cand in "./eda_brief.json" "./analysis_brief.json" "/tmp/eda/eda_brief.json"; do
    [ -f "$cand" ] && BRIEF="$cand" && break
done
```

```
# brief 있으면
Read: $BRIEF
→ premises = {value_scale, audience, use_case}
→ goal = "..."
→ depth = "minimal | standard | deep"
→ focus_sections = [...]
```

**brief 없음** = 사용자가 intake 안 거쳤음 → 의도 C (BROAD EDA) 진입 전에 `Skill(eda-intake)` 로 brief 수집 권장. 단 사용자가 명시적으로 brief 우회 요청 시 (예: "그냥 빠르게 돌려") 진행하되 `depth=standard` + worker 카탈로그 기본값 사용.

## Step 1 — Baseline 분석 (deterministic, 직렬)

세션 디렉토리: `/tmp/eda/<도메인>_<YYYYMMDD>/`

```bash
SESSION=/tmp/eda/<session>
mkdir -p $SESSION

# overview (7 섹션)
python3 <SKILLS>/eda-overview/scripts/run.py <data_path> --out $SESSION/analysis_results.json

# casestudy (TOP10 시리즈)
python3 <SKILLS>/eda-casestudy/scripts/run.py <data_path> --out $SESSION/analysis_results.json --append
```

같은 세션 디렉토리에 결과 있으면 skip (캐싱).

## Step 2 — Inspector (rule-based 사전 검증)

```bash
python3 <SKILLS>/eda/scripts/inspector.py $SESSION/analysis_results.json --json
```

`completeness_score < 0.5` 이면 데이터 자체 문제 — 사용자에게 안내하고 중단.
그 외엔 점수 무관 진행 (실제 검증은 Plan Critic이 함).

## Step 3 — ★ Plan Critic (Agent subagent, opus)

baseline 결과 + 사용자 질문 + (있다면) brief 를 Critic에 넘기고 finding을 받는다.

```
Agent:
  subagent_type: plan-critic
  description: EDA 계획 검토
  prompt: |
    사용자 질문: "$ARGUMENTS"
    세션: $SESSION
    analysis_results.json 경로: $SESSION/analysis_results.json
    Brief premises (있으면): {value_scale: ..., audience: ..., use_case: ...}
    Brief depth: {minimal | standard | deep}
    
    데이터 가정 · 메타데이터 활용 · 누락 축 · 세그먼트 임계값 4축에서 finding을 산출하라.
```

응답은 **단일 JSON 블록**. critic 응답 텍스트를 그대로 파싱:

```bash
# critic 응답을 임시 파일로 받았다고 가정 (실제로는 Agent 결과 텍스트)
echo "$CRITIC_RESPONSE" > /tmp/eda/$SESSION/critic.json

# blocker 추출 (jq 사용)
BLOCKERS=$(jq -r '.findings[] | select(.severity == "blocker") | .recommendation' /tmp/eda/$SESSION/critic.json)
MAJOR_COUNT=$(jq -r '[.findings[] | select(.severity == "major")] | length' /tmp/eda/$SESSION/critic.json)
APPROVED=$(jq -r '.approved_with_changes' /tmp/eda/$SESSION/critic.json)
```

핵심 키:
- `findings[].severity`: blocker / major / minor
- `findings[].axis`, `finding`, `evidence`, `recommendation`
- `approved_with_changes`: blocker 없으면 true

critic이 JSON 외 텍스트를 섞어 보내면 (Iron Law 위반) → 응답에서 첫 `{` ~ 마지막 `}` 구간만 추출 후 재파싱. 그래도 fail 시 critic 단계 skip하고 진행 (trace에 기록).

### 결정 규칙

| Critic 결과 | Lead 행동 |
|---|---|
| blocker 1개 이상 | **반드시 반영** — recommendation 따라 worker 선택 or baseline 재실행 |
| major만 있음 | 반영 권장. worker에 finding을 prompt로 전달 |
| minor만 있음 / 빈 배열 | 참고만, 진행 |

**중복 critic 호출 금지** — 1회 한정. blocker 해결 위해 baseline 재실행하면 critic 재호출은 OK 1회 더.

## Step 4 — Worker (조건부, 최대 1개)

Lean 구조: subagent를 fan-out 하지 않는다. Lead가 직접 분석 + 인사이트 작성. 단 **메타데이터 enrichment가 필요한 경우에만** `worker-content` 를 1개 spawn한다.

**활성 subagent (등록된 것)**:

| Subagent | 모델 | 책임 | spawn 조건 |
|---|---|---|---|
| `plan-critic` | opus | Step 3에서 호출 (위) | 항상 |
| `worker-content` | sonnet | 콘텐츠 + 메타 enrichment (movies.parquet 등 join) | **데이터 디렉토리에 메타 파일이 존재할 때만** |

`worker-content` spawn 조건 — Bash로 먼저 확인:
```bash
META_FILES=$(ls $DATA_PATH/*.parquet $DATA_PATH/*.dat 2>/dev/null | grep -v ratings | head -3)
[ -n "$META_FILES" ] && SPAWN_CONTENT=1
```

spawn하면 `worker_content.md` 가 생성됨 — Step 5에서 Lead가 inline. 미spawn 시 Lead가 `top_content_type_dist` / `pareto_long_tail` 만 직접 해석.

**Archived (지금은 비활성, 필요 시 agents.py `_ARCHIVED_AGENTS` 에서 부활)**: `worker-quality`, `worker-engagement`, `worker-temporal`, `worker-segment-cross`, `insight-reviewer`. 이들의 책임은 Step 5에서 Lead가 직접 흡수 (아래 인라인 규칙).

### worker-content spawn 패턴 (조건부)

메타 파일 존재 확인 후 spawn:

```
Agent:
  subagent_type: worker-content
  description: 콘텐츠 + 메타 enrichment
  prompt: |
    세션 경로: $SESSION
    데이터 경로: $DATA_PATH
    메타 파일 후보: $META_FILES
    사용자 질문: "$ARGUMENTS"
    Brief premises (있으면): {value_scale, audience, use_case}
    Plan Critic finding (관련 항목): {metadata axis blocker/major}
    
    ratings × 메타 join 으로 장르/시대/카테고리 인사이트 작성. worker_content.md.
```

메타 파일 없으면 spawn 생략. Lead가 `top_content_type_dist` / `pareto_long_tail` 만 직접 해석해서 콘텐츠 인사이트 1-2개 산출.

## Step 5 — Lead 직접 분석 + 통합 (★ 핵심 단계, lean 구조)

Lead가 `analysis_results.json` + (있다면) `worker_content.md` 를 읽고 **4개 archived worker의 책임을 직접 흡수**해서 인사이트 5-7개를 작성한다.

```
Read: $SESSION/analysis_results.json
Read: $SESSION/worker_content.md   # spawn된 경우에만
```

### 5-1. 인라인 규칙 (archived worker로부터 흡수)

**A. 스케일 자동 추론 (← worker-quality)**
- `value_describe.max` 로 스케일 결정:
  - max ≤ 1.0 → 0-1 proportion
  - max ≤ 5.0 → 1-5 별점 (ML-1M 등)
  - max ≤ 10.0 → 1-10 별점 (Watcha · value = 별점×2)
  - max > 10.0 → count / aggregated
- 경계 케이스 (max ∈ [4.5, 5.5])는 `value_buckets_pct` 라벨 + `_meta.data_path` 도메인명으로 cross-check
- 인사이트 첫 줄에 **추론한 스케일 명시**. Watcha 1-10 hardcode 금지.

**B. Segment 임계값 재캘리브레이션 (← worker-engagement)**
- 기본 임계값(Light 1-5 / Medium 6-20 / Heavy 21-49 / Power 50+)이 분포에 맞는지 확인
- 한 segment가 **70%+ 차지하면 데이터셋 필터링 인공물 의심** — 인사이트에 반드시 명시 ("min-N 필터링 가능성")
- 분위수(P25/P50/P75/P90) 기반 재정의 권장 (필요 시 구체 숫자)

**C. Cold-start 보정 (← worker-temporal)**
- `daily_volume` 변동 max/min > 1000× 면 **cold-start 의심 명시**. 정상 패턴인 척 지나가지 말 것
- timestamp 의미 (rating event vs viewing event) 데이터셋 출처로 추론. 모호하면 "미확정" 표기
- "저녁대 피크 = 시청 피크" 식 추론 금지 (rating timestamp는 평점 시각이지 시청 시각 아님)
- KST 보정 정합성 확인 (`_meta.period_start/end` 가 한국 시간 패턴인지)

**D. Cross 해석 discipline (← worker-segment-cross)**
- 단일 content_type / 단일 segment 데이터에서 cross-tab "100% / 0%" 트리비얼 표 인용 금지
- 의미 있는 1-2개 패턴만 진술 ("X가 Y일수록 Z가 ..."). 모든 cross 표 옮기지 말 것

**E. ML 용어 풀어쓰기 (공통)**
- Gini / Lorenz / Lift / Cosine 등 첫 등장 시 한 줄 풀이 동반
- 예: "Gini 0.633 (0=평등 · 1=완전 쏠림 · 0.6+는 매우 쏠림)"

### 5-2. dedupe + 선별

- 풀 EDA: **5-7개** 인사이트 (Q&A는 3-5개)
- audience(brief.premises.audience)에 맞춰 톤:
  - DS → 모델링 권장 강조, ML 용어 OK
  - PM → 비즈니스 함의 강조, ML 용어 풀이 동반
  - Infra → 데이터 품질 / 스케일 영향 강조
  - exec → 1줄 결론 중심, 수치 최소
- 같은 수치 반복 금지. 사용자가 묻지 않은 곁가지 제거.

### 5-3. 🚫 Single-Write Iron Law (latency 핵심)

**Lead는 인사이트를 한 번에 통합 완성해서 단일 `Write`/`Edit` 으로 EDA_REPORT.md 에 박는다. 부분/반복 Edit 금지.**

이유: 매 Edit = API roundtrip ~3-5s + LLM turn. 15 Edit = 60-90s 낭비. 한 번에 끝.

**올바른 패턴**:
1. Lead가 메모리에서 5-7개 인사이트 작성 완료 (텍스트 한 덩어리로)
2. deterministic 리포트(render_full_report.py 출력)의 `<!-- LLM_DEEP_INSIGHT_START -->` ~ `<!-- LLM_DEEP_INSIGHT_END -->` placeholder 자리를 **단일 Edit** 으로 교체
3. 그 외 보강이 필요하면 (예: 스케일 hardcoded 오류 — render 스크립트가 1-10 가정인데 실제 1-5) **모든 보강 사항을 합쳐 단일 Write** 로 EDA_REPORT.md 전체 재작성

**잘못된 패턴 (금지)**:
- 인사이트 1개 작성 → Edit → 인사이트 2개 → Edit ... ❌
- case_studies 별점 1개씩 수정 → 여러 Edit ❌
- placeholder Edit 후 별도 Edit 으로 다른 섹션 손질 ❌

### 5-4. Deterministic 리포트 생성

```bash
python3 <SKILLS>/eda-figures/scripts/render.py $SESSION/analysis_results.json --output $SESSION/figures
python3 <SKILLS>/eda-report/scripts/render_full_report.py $SESSION/analysis_results.json --figures-dir $SESSION/figures --out $SESSION/EDA_REPORT.md
```

EDA_REPORT.md의 `<!-- LLM_DEEP_INSIGHT_START -->` ~ `<!-- LLM_DEEP_INSIGHT_END -->` placeholder를 `Edit` tool로 교체:
- 내용 = worker_*.md 합본 + Lead의 상위 통합 인사이트 1-2개
- 형식 = `llm_insight_pattern.md` 따름

## Step 6 — Lead Self-Check (← insight-reviewer 책임 흡수)

Reviewer subagent 없이 Lead가 사용자에게 보내기 직전 다음 체크리스트를 직접 통과해야 한다. 항목 위반 시 `Edit`으로 EDA_REPORT.md 수정 후 재검사 (최대 1회).

**4 issue 타입 self-scan**:

| 타입 | 체크 | 대표 위반 예시 |
|---|---|---|
| **trivial** | 의미 없는 수치 / 단일 type 데이터에서 "Movie 100%" | "상위 1% Movie 100%" |
| **duplicate** | 같은 수치/해석이 다른 섹션에서 반복 | sparsity 95% 가 3번 등장 |
| **jargon** | Lift / Gini / Lorenz / Cosine 등 풀이 없이 사용 | "Gini 0.633" 단독 |
| **offtopic** | brief.use_case와 무관한 곁가지 | DS 용 리포트인데 마케팅 함의 |

**Self-Check 결정 규칙 (🚫 Single-Edit Iron Law)**:

- 4타입 모두 한 번에 검사 → 발견된 issue **전부 한 덩어리로 정리**
- 수정이 필요하면 **단일 Edit (혹은 단일 Write로 전체 재작성)** 으로 모든 issue 를 한 번에 fix
- 부분 / 반복 Edit 금지 — 매 Edit 마다 ~3-5s API 비용 + LLM turn 낭비
- 수정 후 재검사 없음 (재검사가 또 다른 Edit 을 부르는 함정). 한 번에 잘 할 것.
- 수정 없으면 바로 Step 7

**예시**:
- ✅ 좋은 Edit: trivial 1개 + duplicate 2개 + jargon 1개 = 총 4개 fix 를 한 Edit 으로 합쳐 처리
- ❌ 금지: trivial fix Edit → duplicate fix Edit → jargon fix Edit (3 별도 Edit)

trace 기록:
```bash
python3 <SKILLS>/eda/scripts/trace.py $SESSION --step self_check --decision "issues=N · single_edit=yes/skipped"
```

## Step 7 — 사용자에게 보고

PANDA 형식, 80~150줄:

```markdown
🐼 [질문 1줄 요약]

📅 [핵심 표 1-2개]

📊 **집계 기준**
- 데이터 / 기간(KST!) / 행 수 / 기준

---

💡 **주요 인사이트** (5-7개)

✓ **[결론 1]**
- 수치 부연
- 짧은 해석

✓ **[결론 2]**
- ...

📁 상세: $SESSION/EDA_REPORT.md
```

상세 표 / 차트는 본문에 박지 말고 **경로만 안내**.

---

# INTERPRETIVE Q&A 모드 (의도 B) — Fast Path

해석/패턴/도메인 질문. 캐시 가능하면 재사용, 단 **fingerprint 검증 필수**.

## Step B-1. 사용자 요청 파라미터 추출

질문에서 다음을 추출 (있는 것만):
- `REQUESTED_PATH` — 데이터 경로 (있으면)
- `REQUESTED_START`, `REQUESTED_END` — 기간 필터 (있으면)
- `REQUESTED_FILTER` — segment / type 필터 (있으면)

명시 안 됐으면 None.

## Step B-2. 캐시 후보 탐색 + Fingerprint 검증

```bash
EXISTING=$(ls -t /tmp/eda/*/analysis_results.json 2>/dev/null | head -1)

if [ -n "$EXISTING" ]; then
    # _meta 추출 (단일 jq 호출로)
    CACHE=$(jq -r '._meta | {data_path, period_start, period_end, key_metric}' "$EXISTING")
    CACHE_PATH=$(echo "$CACHE" | jq -r '.data_path')
    CACHE_START=$(echo "$CACHE" | jq -r '.period_start')
    CACHE_END=$(echo "$CACHE" | jq -r '.period_end')
    
    # Fingerprint 매칭 (3가지 다 만족해야 reuse 안전):
    PATH_OK=false
    PERIOD_OK=false
    
    # 1) data_path: REQUESTED_PATH 가 None 이거나 CACHE_PATH 와 매칭
    [ -z "$REQUESTED_PATH" ] || [ "$REQUESTED_PATH" = "$CACHE_PATH" ] && PATH_OK=true
    
    # 2) period: REQUESTED 가 None 이거나 CACHE 범위에 ⊆ 포함
    if [ -z "$REQUESTED_START" ]; then
        PERIOD_OK=true   # 사용자가 기간 명시 안 함 = 캐시 그대로 OK
    elif [ "$REQUESTED_START" \>= "$CACHE_START" ] && [ "$REQUESTED_END" \<= "$CACHE_END" ]; then
        PERIOD_OK=true   # 사용자 요청 기간이 캐시 기간에 포함
    fi
    
    if $PATH_OK && $PERIOD_OK; then
        SESSION=$(dirname "$EXISTING")
        echo "✓ cache hit: $SESSION"
    else
        echo "✗ fingerprint mismatch — rebuild 필요"
        echo "  REQUESTED: path=$REQUESTED_PATH period=$REQUESTED_START~$REQUESTED_END"
        echo "  CACHE:     path=$CACHE_PATH period=$CACHE_START~$CACHE_END"
        EXISTING=""  # rebuild trigger
    fi
fi
```

## Step B-3. 캐시 mismatch → Rebuild (또는 캐시 없음)

```bash
if [ -z "$EXISTING" ]; then
    DATA_PATH="${REQUESTED_PATH:-?}"
    [ "$DATA_PATH" = "?" ] && {
        # AskUserQuestion 1회: 경로 묻기
        :
    }
    SESSION=/tmp/eda/$(basename "$DATA_PATH")_$(date +%Y%m%d_%H%M%S)
    mkdir -p $SESSION
    python3 <SKILLS>/eda-overview/scripts/run.py "$DATA_PATH" --out $SESSION/analysis_results.json
    python3 <SKILLS>/eda-casestudy/scripts/run.py "$DATA_PATH" --out $SESSION/analysis_results.json --append
fi
```

## Step B-4. Q&A 답변 작성

Lead가 `analysis_results.json` 의 관련 키만 읽고 (`case_studies` / `pareto_long_tail` / `user_segments` / 등) **PANDA 형식 30-50줄 답변**.

```bash
# (옵션) render_qa.py 활용
python3 <SKILLS>/eda-report/scripts/render_qa.py $SESSION/analysis_results.json \
    --question "$ARGUMENTS" --out $SESSION/QA.md
```

Lead가 QA.md 그대로 출력 또는 핵심 압축.

## 🚫 Iron Laws

- **Fingerprint 검증 누락 금지** — `ls -t | head -1` 만으로 캐시 잡지 말 것. 기간/경로 mismatch 시 잘못된 답.
- **NARROW 질문은 의도 A로 즉시 전환** — TOP N / 분포 / 카운트는 Q&A 거치지 말고 직접 pandas.
- **Subagent spawn 금지** — Critic / Reviewer / Worker 다 skip. Lead가 직접 답.
- **Bash 호출 ≤ 3회** — fingerprint 검증 1 + (rebuild이면) script 2 = 최대 3

---

## 세션 / 산출물

```
/tmp/eda/<session>/
├── analysis_results.json   # baseline (deterministic)
├── worker_quality.md       # worker 출력
├── worker_engagement.md
├── figures/F1*.png ...
├── EDA_REPORT.md           # 최종 리포트
└── trace.jsonl             # observability (있다면)
```

trace 기록 (각 step 후):
```bash
python3 <SKILLS>/eda/scripts/trace.py $SESSION --step <step> --decision <summary>
```

---

## Sub-skill 위치 탐색

레이아웃은 두 가지 — MOCHA(vendored) 우선, marketplace 대안:

```bash
# MOCHA — eda 플러그인이 앱에 vendored
SKILLS_ROOT=$(find . -path "*/plugins/eda/skills" -type d 2>/dev/null | head -1)

# 못 찾으면 marketplace cache
[ -z "$SKILLS_ROOT" ] && SKILLS_ROOT=$(find ~/.claude -path "*/eda/skills" -o -path "*/ml-dev-skills/skills" -type d 2>/dev/null | head -1)
```

각 sub-skill: `$SKILLS_ROOT/eda-{name}/scripts/run.py`

---

## 진행 로그 형식

사용자에게 보여주는 짧은 상태:

```
[0/6] Brief 로드 ... ✓ depth=standard · premises 확인
[1/6] Baseline ... ✓ (overview · casestudy)
[2/6] Plan Critic ... ✓ 2 findings (1 blocker · 1 major)
[3/6] worker-content (조건부) ... ✓ enrichment (장르 · 시대)
[4/6] Lead 분석 + 인사이트 작성 (5-7개) ... ✓
[5/6] Self-check (trivial/duplicate/jargon/offtopic) ... ✓ pass
[6/6] 사용자 답변 ... ✓
```

(메타 파일 없으면 [3/6] 생략 → 5단계. 예상 wall-clock: **1.5-2분**)

---

## 핵심 가드레일 (lean 구조)

- **Subagent fan-out 금지** — Critic 1회 + worker-content (조건부 1회) 외엔 spawn 하지 말 것. 나머지는 Lead 직접.
- **🚫 Single-Edit/Write Iron Law** — Lead가 EDA_REPORT.md 손볼 때 **반드시 한 번에**. 부분/반복 Edit 금지. 매 Edit ~3-5s 낭비. 인사이트 / 보강 / self-check fix 전부 합쳐 단일 Edit 또는 단일 Write로 전체 재작성.
- **Plan Critic 권한 = advisory** — blocker만 반드시 반영
- **Self-check 권한 = advisory** — 4 타입 issue 모두 검출 후 **한 번에 fix**. 재검사 없음.
- **재시도 한도**: Critic 1회 · worker-content 1회 · Self-check Edit 1회
- **Hardcode 금지**: value 스케일 / segment threshold / cold-start 가정 — Lead가 Step 5 인라인 규칙으로 데이터로 추론
- **Archived workers (5종) 부활 조건**: 사용자가 명시적으로 "deep mode" 요청 + 결과가 부족 시 (`agents.py _ARCHIVED_AGENTS` 에서 `AGENTS` 로 이동)
- **Trace 기록**: 각 step 후 1줄 — observability + 사후 디버깅

---

## Resources

### Scripts
- `scripts/inspector.py` — 사전 검증 (rule-based)
- `scripts/trace.py` — observability

### References
- `references/agentic_loop.md` — 루프 디자인 상세
- `../eda-report/references/llm_insight_pattern.md` — Deep Insight 작성 가이드 (필수)
