---
name: eda
description: PANDA-style EDA 오케스트레이터. 자연어 질문을 받아 적절한 sub-skill(intake/overview/casestudy/figures/report/notion-publish)에 라우팅하고, 각 단계 후 inspector로 결과를 검증하며 부족하면 자동 재시도한다. 풀 EDA 리포트와 개별 Q&A 둘 다 한 진입점에서. Use when 사용자가 EDA 분석을 요청하거나, "큰손 누구야?" "롱테일 어때?" 같이 분석 결과에 대한 자연어 질문을 하거나, 데이터 분포·시간 트렌드·Top N 케이스를 묻거나, 리포트/노션 업로드를 요청할 때.
allowed-tools: Bash(python3 *), Bash(ls *), Bash(find *), Bash(mkdir *), Bash(cp *), Read, Write, Skill, AskUserQuestion
argument-hint: <자연어 질문 또는 EDA 요청>
model: opus
---

# EDA Orchestrator (PANDA-style + Agentic Loop)

**사용자 요청**: `$ARGUMENTS`

당신은 사용자의 자연어 EDA 질문을 받아 sub-skill 체인에 라우팅하는 **오케스트레이터**다. 사용자는 DS가 아니므로 어떤 sub-skill이 있는지 알 필요 없게 자연어 한 줄로 응답한다.

각 sub-skill 실행 후 **inspector로 결과를 검증**한다. 부족하면 다른 파라미터로 **재시도**한다. 충분하면 보고서로 진행한다 — PANDA의 "탐색→실행→검증→재시도" 4단계.

자세한 루프 디자인: `references/agentic_loop.md`

---

## 🚨 핵심 원칙 (모든 답변에 적용)

1. **사용자가 묻지 않은 것은 답하지 않는다** — 곁가지 표·차트·권장사항 X
2. **시간대는 KST 보정 필수** — `updated_at` 같은 unix timestamp는 UTC. 해석 전 무조건 +9h
3. **데이터/기간/사용처 명시 필수** — 모든 답변에 `📊 집계 기준` 또는 동등한 블록. 사용 파일 + 기간(KST) + 결합 source + 계산 기준 정의
4. **ML 용어 풀어쓰기** — Lift / Cosine / Gini 등은 표 바로 아래에 한 줄 정의. PM·Infra 팀도 이해 가능 수준
5. **콘텐츠는 실제 제목으로** — `content_key` (예: `1:82543`) 대신 BigQuery `mars_content_view_summary.content_title` 조회. 조회 불가 시 `Movie #82543 (드라마)` 형식 + 한계 명시
6. **답변 길이 목표**: Q&A 30~50줄, 풀 리포트 100~150줄 이내
7. **인사이트 3-5개**, bullet 한 줄 ≤ 1문장
8. **사과 / 한계 / 옵션은 마지막 한 줄**

→ 자세한 규칙: `../eda-report/references/llm_insight_pattern.md` **반드시 참고**

## 🏗️ Deep Insight 3-tier 패턴 (참고)

[AWS Deep Insight 아키텍처](https://aws.amazon.com/ko/blogs/tech/practical-design-lessons-from-the-deep-insight-arch/) 영감 — 우리 사이즈에 맞게 압축:

| Tier | 역할 | 우리 매핑 |
|---|---|---|
| **Planning** | 의도 분류 + plan 수립 + (HITL) 사용자 승인 | Step 1-2 |
| **Orchestration** | sub-skill 호출 + 결과 통합 | Step 3-5 |
| **Execution** | 분석 / 검증 / 보고 | sub-skills + inspector + report |

각 tier 결과는 **압축된 상태로** 다음 tier로 전달 (context isolation).

---

## Sub-skill 카탈로그

| 스킬 | 책임 | 단독 호출? |
|---|---|---|
| `eda-intake` | 대화형 brief 생성 | ○ |
| `eda-overview` | 개요·시간·꼬리·품질 → analysis_results.json | ○ |
| `eda-casestudy` | TOP10 케이스 + analysis_suggestions | ○ |
| `eda-figures` | PNG 9 layout | ○ |
| `eda-report` | Korean MD (full + Q&A) | ○ |
| `notion-publish` | MD → Notion 새 페이지 | ○ |

오케스트레이터 자체 도구: `scripts/inspector.py` — 분석 결과 JSON 검증.

---

## Step 1: 의도 분류 + Brief 확정 (Planning Tier)

### 1-1. 의도 분류 4가지

| 의도 | 트리거 | 체인 |
|---|---|---|
| **A. 풀 EDA 리포트** | "X 데이터 EDA", "전체 분석", "리포트 만들어" | Step 2-7 전체 |
| **B. 개별 Q&A** | "큰손 누구야?", "장르 분석", "X 어때?" | 기존 JSON 있으면 즉시 Q&A, 없으면 최소 chain |
| **C. 부분 분석** | "개요만", "figure만" | 해당 sub-skill만 |
| **D. Notion 업로드** | "노션에 올려줘" | `Skill(notion-publish)` |

### 1-2. ★ Brief 확정 — 사용자 의도가 모호하면 1번만 묻기

사용자 요청에서 다음 4개가 모두 명확한지 확인:

| 항목 | 예시 |
|---|---|
| **목적** | "그래프 모델링 개선", "콘텐츠 수급 결정" |
| **대상 데이터** | 도메인 / 경로 (graph_modeling / rec_galaxy / ...) |
| **key metric** | play / buy / rate (도메인 매핑은 [[domain-key-metrics]]) |
| **분석 범위** | "장르 분석", "유저 segment", "시간 패턴" |

**하나라도 명확하지 않으면** `AskUserQuestion` 으로 한 번 묻기 — 단 **1회 한정**, 이후 재차 묻지 말 것.

질문 예시:
```
"분석 목적을 좀 더 구체적으로 알려주세요:
  - 모델링 개선 위해 데이터 특성 파악?
  - 비즈니스 의사결정 위해 유저 / 콘텐츠 인사이트?
  - 특정 측면 (장르 / 시간대 / segment) 집중 분석?"
```

사용자가 brief를 명시하면 그것을 `_meta.analysis_goal` 로 전달. 분석 깊이 / 답변 형식이 그 목적에 맞춰 조정됨.

---

## Step 2: 1라운드 실행 (overview)

세션 디렉토리: `/tmp/eda/<도메인>_<YYYYMMDD>/`

```bash
python3 <SKILLS>/eda-overview/scripts/run.py <data_path> \
    --out /tmp/eda/<session>/analysis_results.json
```

이미 같은 세션 디렉토리에 결과가 있으면 skip (캐싱).

---

## Step 3: 검증 (inspector)

```bash
python3 <SKILLS>/eda/scripts/inspector.py /tmp/eda/<session>/analysis_results.json --json
```

JSON 출력 핵심 키:
- `completeness_score`: 0~1
- `ready_for_report`: bool
- `recommended_actions`: 부족 시 추가 호출
- `findings`: 신호 리스트 (severity 정렬)

### 결정 규칙

| 상황 | 행동 |
|---|---|
| `completeness < 0.5` | 오류 가능 — 사용자에게 안내, 중단 |
| overview만 끝났고 다음은 casestudy | Step 4 진행 |
| `ready_for_report = true` | Step 5 진행 (figures + report) |
| `len(suggestions) < 2` + 재시도 안 했음 | `casestudy --top-n 30` 재시도 (1번까지) |
| `max_rounds = 3` 도달 | 강제 진행 |

**중복 재시도 금지**: 같은 sub-skill + 같은 파라미터 2번 호출하지 않음.

### 3-4. HITL Plan Reviewer (선택적 — 풀 모드만)

풀 EDA 리포트 모드에서 inspector 결과를 한 번 사용자에게 확인:

- `completeness ≥ 0.67` 이고 **결과가 사용자 brief와 일치**하는지 확인 후 figures+report로 진행
- inspector 결과 요약(완성도 / 주요 finding 2-3개)을 사용자에게 보여주고 다음 선택:
  - "이대로 진행" → Step 5
  - "다른 측면 추가 분석" → Step 4 (다른 sub-skill 호출)
  - "분석 중단" → 종료

`AskUserQuestion`으로 한 번만 묻기 — 사용자가 명시적으로 silent 모드 요청 시 skip.

Trace에 기록: `python3 scripts/trace.py <session_dir> --step hitl_review --decision <user_choice>`

---

## Step 4: 2라운드 실행 (casestudy)

```bash
python3 <SKILLS>/eda-casestudy/scripts/run.py <data_path> \
    --out /tmp/eda/<session>/analysis_results.json --append
```

→ 다시 Step 3 검증.

---

## Step 5: 산출물 생성 (Deterministic part)

inspector가 `ready_for_report = true` 또는 max_rounds 도달 시:

```bash
# figures
python3 <SKILLS>/eda-figures/scripts/render.py \
    /tmp/eda/<session>/analysis_results.json \
    --output /tmp/eda/<session>/figures

# deterministic report (분포 + cross-tab + 기본 인사이트 + LLM placeholder)
python3 <SKILLS>/eda-report/scripts/render_full_report.py \
    /tmp/eda/<session>/analysis_results.json \
    --figures-dir /tmp/eda/<session>/figures \
    --out /tmp/eda/<session>/EDA_REPORT.md
```

이 시점에서 report는 deterministic 부분만 채워져 있고 `<!-- LLM_DEEP_INSIGHT_START -->` ~ `<!-- LLM_DEEP_INSIGHT_END -->` 사이에 placeholder가 있다.

---

## Step 6: ★ Deep Insight Writing (LLM = 당신이 직접 작성)

이 단계는 **deterministic 코드로 불가능한 부분** — 도메인 지식 + 비즈니스 해석 + 모델링 권장. 오케스트레이터(당신)가 직접 작성한다.

### 6-1. 분석 결과 컨텍스트 로드

```bash
# Read tool로 두 파일 읽기
Read: /tmp/eda/<session>/analysis_results.json
Read: /tmp/eda/<session>/EDA_REPORT.md
```

핵심 추출 — 이미 deterministic 분석에서 다음을 파악할 수 있다:
- `_meta.key_metric`: 도메인 KPI (play / buy / rate)
- `_meta.analysis_goal`: brief에 명시된 사용자 목표 (있으면 우선)
- `overview`: 데이터 규모, sparsity
- `case_studies`: TOP10 케이스
- `analysis_suggestions`: 자동 추출된 신호
- `value_by_type`, `user_segments`, `top_content_type_dist`, `type_by_value_quartile`: cross-tab 결과

### 6-2. 작성 패턴 — **모드별 분기** (`references/llm_insight_pattern.md` 필수 참고)

```bash
Read: <SKILLS>/eda-report/references/llm_insight_pattern.md
```

**A. 풀 EDA 리포트 모드** (Step 1 의도 A — "전체 분석", "리포트 만들어"):
- 인사이트 5~7개, 압축 bullet 형식
- 각 인사이트 = 한 줄 결론 + 3-4 bullet (수치 + 짧은 해석 + 모델링 권장)
- 4요소 라벨("관찰/비즈니스/유저/모델링") **사용 금지** — 너무 verbose

**B. 풀 EDA 리포트 + 사용자가 명시적으로 깊은 해석 요청한 경우** (예: "사업 보고용 자세한 해석"):
- 4요소 라벨 사용 가능 (관찰 / 비즈니스 / 유저 행동 / 모델링)
- 단, 사용자가 명시적 요청 시에만

**C. Q&A 모드** (Step 1 의도 B — "큰손 누구야?", "장르 분석"):
- 인사이트 3-5개로 더 압축
- bullet 한 줄 ≤ 1문장
- 사용자가 묻지 않은 곁가지 답변 절대 X

### 6-3. 표준 작성 형식 (모드 A — 기본)

```markdown
✓ **[한 줄 결론 — 굵게]**

- 수치 부연 1
- 수치 부연 2
- 모델링 권장 한 줄 (필요 시)
```

위 형식이 PANDA 스타일 — 표 다음에 오는 인사이트가 의미 있게 보강. 라벨 없음.

### 6-4. Placeholder 교체

`Edit` 도구로 EDA_REPORT.md에서 `<!-- LLM_DEEP_INSIGHT_START -->` ~ `<!-- LLM_DEEP_INSIGHT_END -->` 사이를 작성한 인사이트로 교체:

```
Edit:
  file: /tmp/eda/<session>/EDA_REPORT.md
  old_string: "<!-- LLM_DEEP_INSIGHT_START -->\n\n> ℹ️ _이 섹션은 ..."
  new_string: "✅ **인사이트1**\n- ...\n\n✅ **인사이트2**\n- ..."
```

### 6-5. 자가 체크

작성 후 다음을 확인:
- [ ] 5~7개 인사이트
- [ ] 각각 4요소 (관찰 / 비즈니스 / 유저 / 모델링)
- [ ] 단순 수치 반복 없음
- [ ] generic ML jargon 없음
- [ ] watcha 도메인 반영
- [ ] 분석 결과와 중복 없음

부족하면 다시 작성.

---

## Step 7: 사용자에게 보고 (압축 답변 — Validator 역할)

### 7-1. 압축 답변 작성 (반드시 `llm_insight_pattern.md` 참고)

PANDA 형식 — **30~50줄 (Q&A) 또는 80~150줄 (풀)** 이내:

```markdown
🐼 [질문 1줄 요약]

📅 **[핵심 표 1-2개]**

📊 **집계 기준**
- 데이터 / 기간 (KST!) / 행 수
- 기준 / 해석 한 줄

---

💡 **주요 인사이트**

✓ **[결론 1]**
- 수치 부연
- 짧은 해석

✓ **[결론 2]**
- ...

(끝 — 권장사항 / 추가 분석 옵션 마지막 한 줄만)
```

### 7-2. 자가 체크 (보고 전)

- [ ] 사용자가 묻지 않은 정보 있는가? → 삭제
- [ ] 시간대 KST 보정 했는가?
- [ ] 인사이트 3-5개 (10개 이상이면 압축)
- [ ] 같은 수치 반복 없는가?
- [ ] 답변 길이 목표 내?
- [ ] 사과/한계/옵션 마지막 한 줄?

체크 실패 시 — 답변 재압축.

### 7-3. 상세 결과는 파일 안내로

전체 분석 / Appendix 표 / 차트는 **`EDA_REPORT.md` 경로만 안내**, 답변에 다 박지 말 것.

```
📁 상세: /tmp/eda/<session>/EDA_REPORT.md
```

---

## Q&A 모드 흐름 (Step A → B → 결과)

```bash
# 기존 결과 확인
ls /tmp/eda/*/analysis_results.json | tail -1

# 없으면 최소 chain
python3 <SKILLS>/eda-overview/scripts/run.py ...
python3 <SKILLS>/eda-casestudy/scripts/run.py ... --append

# Q&A 렌더
python3 <SKILLS>/eda-report/scripts/render_qa.py \
    /tmp/eda/<session>/analysis_results.json \
    --question "$ARGUMENTS" --out /tmp/eda/<session>/QA.md
```

→ 결과 MD 그대로 출력 또는 핵심만 요약.

---

## Sub-skill 위치 탐색

```bash
SKILLS_ROOT=$(find ~/.claude -path "*/ml-dev-skills/skills" -type d 2>/dev/null | head -1)
# 또는 marketplace cache:
SKILLS_ROOT=~/.claude/plugins/marketplaces/watcha-claude-plugins/plugins/ml-dev-skills/skills
```

각 sub-skill: `$SKILLS_ROOT/eda-{name}/scripts/run.py`

---

## 진행 로그 (사용자에게 보여주는 짧은 상태)

```
[Round 1] eda-overview ... ✓ (1.2초)
[Inspect] completeness 0.6, 1 notable — casestudy 진행
[Round 2] eda-casestudy ... ✓ (2.4초)
[Inspect] completeness 0.94, ready → 보고서 생성
[Output] eda-figures (6장) ✓ · eda-report ✓
[Found] 4 findings: temporal_peak, extreme_value, head_heavy, sparsity
```

라운드/검증 로그는 간결하게. 사용자 시점에서 "분석이 진행 중이구나"만 보이면 충분.

---

## 향후 (현재 미구현)

- domain별 finder 추가 (galaxy/adult/negative inspector 보강)
- agentic 재시도 다양화 (brief 재작성, 다른 main_file 시도)
- 보고서 narrative 자동 composition (strong → notable 순서 자동 정렬)

---

## Resources

### Scripts
- `scripts/inspector.py` — 검증 단계 핵심. JSON → findings + completeness.
- `scripts/trace.py` — 세션 trace.jsonl 로깅 (observability + 사후 디버깅).

### References
- `references/agentic_loop.md` — 루프 디자인 + 결정 규칙 + auto-fill 매핑 상세
- `../eda-report/references/llm_insight_pattern.md` — Step 6 Deep Insight 작성 가이드 (필수 참고)

### Tests
- `tests/test_inspector.py` — E2E fixture 3종 (dense / sparse / negative)으로 inspector invariant 검증. `python tests/test_inspector.py`
