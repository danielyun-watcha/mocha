# 🎤 천하제일 AI 자랑대회 — MOCHA 발표 (10분)

> **행사**: 월간플랫폼 #5 — 천하제일 AI 자랑대회
> **발표자**: daniel (ML Engineer)
> **주제**: MOCHA ☕ — 자연어로 묻는 Watcha 데이터 분석 AI
> **톤**: ML 엔지니어 전문성 + 약간의 위트 (실패담 인정형)
> **청중**: 혼합 (기술 + 비기술)

---

## 📐 전체 흐름 (10페이지 / 10분)

| # | 슬라이드 | 시간 | 핵심 메시지 |
|---|---|---|---|
| 1 | Hook — "분석할 때마다 다른 결과" | 0:45 | 동기부여 (자조 → 결심) |
| 2 | MOCHA 한 줄 소개 + 데모 (현장) | 1:30 | "한국어로 묻기 → 5초 답" |
| 3 | 최종 Agent 구조 (Gateway → Fast/Slow) | 1:30 | 아키텍처 청사진 |
| 4 | 진화 1 — multi-agent 실패담 | 0:45 | "처음엔 유행 따라갔다" |
| 5 | 진화 2 — Single Lead + Gateway로 회귀 | 0:45 | "단순한 게 정답" |
| 6 | Templates & Skills — 일정한 결과의 비결 | 1:30 | A/B test · EDA 표준화 |
| 7 | **CAVEMAN 전략** (핵심) | 2:00 | 영어 telegraphic + JSON minify |
| 8 | OAuth Direct + 다단 캐시 | 0:45 | 5-8초 응답의 또 다른 비결 |
| 9 | Iron Rule + PANDA 답변 | 0:30 | 도메인 격리 + 인사이트 강제 |
| 10 | 향후 계획 (Phase 2~4 + panda) | 0:30 | 클로징 |

---

## 슬라이드별 상세

### 📄 슬라이드 1 — Hook

**제목**: 매번 분석 결과가 다른 이유, 아시나요?

**본문 (불릿)**:
- 같은 도메인, 같은 기간, 다른 사람 → 결과 다름
- 같은 사람, 다른 주, 같은 도메인 → 또 다름
- 소수점 · 집계 기준 · 필터 · 시간대(UTC vs KST) 다 다름
- ML 인사이트가 "분석가 컨디션"에 좌우되는 현실

**발표 멘트 (자조 톤)**:
> "ML 엔지니어로서 데이터 분석 결과로 인사이트를 얻는데, 매번 결과가 다르면 그게 인사이트일까요 점일까요? 그래서 만들었습니다. **MOCHA — 자연어로 묻는 Watcha 데이터 분석 AI**."

**시각자료 가이드**: 같은 질문 → 3개의 다른 답 비교 이미지 (또는 메모지 3장 위에 다른 숫자)

---

### 📄 슬라이드 2 — MOCHA란?

**제목**: MOCHA — "한국어 한 줄, 5초 안에 분석 + 인사이트"

**본문**:
- FastAPI + claude-agent-sdk 기반 챗봇 & KPI 대시보드
- **3개 도메인 자동 라우팅**: 왓챠피디아 / 왓챠 / 성인+
- **PANDA 답변 형식** (Toss PANDA 영감): 질문 요약 → 표/차트 → 집계 기준 → 💡 인사이트 1줄
- **자주 보는 KPI는 도메인별 대시보드로 매일 업데이트**

**발표 멘트**:
> "데모 한 번만 보여드릴게요. (현장에서 누름) — '왓챠 최근 30일 TOP10 영화' 묻고 5초 안에 표 + 차트 + 인사이트가 뜹니다."

**시각자료**: 채팅 UI 스크린샷 + 차트 1개

---

### 📄 슬라이드 3 — 최종 Agent 구조

**제목**: 2-Track Gateway 아키텍처

**다이어그램**:

```
사용자 질문 (chat UI)
        ↓
┌────────────────────────────────────────────┐
│ 🚦 Gateway (Haiku 4.5, 1턴, ~6초)          │
│  ├─ track:  fast | slow                    │
│  ├─ intent: narrow_top_n | broad_eda | ... │
│  └─ domain: galaxy | mars | adult | ml_1m  │
└────────────────────────────────────────────┘
        ↓                       ↓
🏎️ Fast Track            🐢 Slow Track
(5-21초)                  (30-120초)
- KPI inline              - Lead Sonnet
- OAuth direct            - Skills 호출
- 단순 통계               - A/B · EDA 보고서
        ↓                       ↓
   PANDA 답변 (표 + 차트 + 💡 인사이트)
```

**왜 이렇게 짰나 (한 줄씩)**:
- "복잡한 질문 < 1%, 단순 질문 99%" → 빠른 길 분리가 비용 효율적
- Gateway는 Haiku로 — 분류만 잘하면 됨
- Slow Track은 Sonnet + Skills/Templates 활용

---

### 📄 슬라이드 4 — 진화 여정 ①: 유행을 좇아 multi-agent

**제목**: 처음엔 요즘 유행이라는 multi-agent 구조로 짰습니다

**본문**:
- "Orchestrator + Subagent 4명 fan-out + Reviewer" 시도
- **테스트 질문**: "galaxy 1년치, 가장 인기 있던 영화 TOP10"
- **결과**: 너무 오래 걸림. agent끼리 토큰 핑퐁만 함
- 현재는 `plugins/eda/.archived/` 로 보존 처리 🪦

**발표 멘트**:
> "agent 4명이서 '내가 할게' '아냐 내가 할게' 하다가, 사용자는 그냥 pandas 한 줄이면 끝낼 걸 60초 기다리고 있었습니다."

---

### 📄 슬라이드 5 — 진화 여정 ②: Single Lead + Gateway로 회귀

**제목**: 단순한 게 정답이었습니다

**비교 표**:

| | Phase 0 (multi-agent) | Phase 1 (현재) |
|---|---|---|
| 구조 | Orchestrator + 4 subagents | Gateway + Single Lead |
| TOP10 1년치 응답 | ~60초+ | **5-8초** |
| 비용 | $0.3+ | ~$0.05 |
| 디버깅 난이도 | 지옥 | 보통 |

**핵심**: agent 수가 많을수록 똑똑한 게 아님. **분기 명확 + Lead 풍부 컨텍스트**가 더 빠름.

---

### 📄 슬라이드 6 — Templates & Skills (신뢰도의 비결)

**제목**: 매번 같은 형식, 매번 같은 신뢰도

**4 Templates** — Lead가 질문 보고 자동 선택:

| 분량 | 템플릿 | 사용 케이스 |
|---|---|---|
| 30-50줄 | `01_light_memo.md` | TOP N · 분포 · 단순 통계 |
| 150-300줄 | `02_full_eda.md` | 전반 EDA · 데이터 특성 |
| 200-400줄 | `03_ab_test.md` | A/B test 사후 (DID + 헤비유저 분리) |
| 100-200줄 | `04_analysis_report.md` | 중간 분석 노트 |

**6 Skills** — 독립 호출:
`eda-overview` / `eda-casestudy` / `eda-figures` / `eda-report` / `eda-intake` / `notion-publish`

**왜 이렇게 짰나**:
- A/B test 템플릿은 실제 **Rec Adult Diff A/B test** 노션 페이지 구조를 그대로 코드화
- EDA 템플릿은 **성인+ / galaxy EDA** 노션 페이지 구조 그대로
- → **"같은 질문 → 같은 형식 → 신뢰도 ↑"**

**시각자료**: `03_ab_test.md`의 헤더 부분 스크린샷 (4분류 KPI 체계 + DID + SRM 체크 등)

---

### 📄 슬라이드 7 — 🦴 CAVEMAN 전략 (핵심 슬라이드)

**제목**: CAVEMAN — agent끼리는 원시인처럼 말한다

**아이디어**:
- "원시인(caveman) 단어 몇 개로 따그문 소통하듯" — agent 내부 로직 / agent 간 소통은 **영어 telegraphic**
- 사용자 노출되는 답변만 **한국어**
- (참고 GitHub link 첨부 위치)

**실제 코드 주석** (`main.py`):

```python
# main.py:1139
# Gateway hint passed to Lead (telegraphic — internal logic,
#  output stays Korean)

# main.py:1196
# Internal logic in English (token-efficient); output forced to Korean.
```

**실제 SYSTEM_PROMPT 일부** (`main.py:193~`):

```
You are MOCHA — Watcha internal data analyst. Answer in **Korean**.

## RULE 1: ONE Bash call (single Python block). NO scouting/head/dtype/retry.
## DOMAIN (Gateway-assigned — access only this archive scope)
{domain_block}
IRON RULE: never read outside the archive paths above.
```

**Gateway prompt** (Haiku용 — 더 압축적):

```
JSON only. `{...}`. No prose/fences.
Schema: {"track":"fast|slow","intent":"narrow_top_n|...","domain":"..."}
Track: narrow_*/interpretive_qa→fast. broad_eda/ab_test→slow.
```

**효과** (PPT에 큰 숫자로):
- 영어 prompt → 한국어 대비 토큰 **~30% ↓**
- JSON minify (`separators=(",",":")` ) → 추가 **20-30% ↓**
- 도메인별 동적 주입 (5개 행 → 1개 행) → 추가 **~40% ↓**
- **합계: input token ~60-70% 절감**

---

### 📄 슬라이드 8 — 속도 비결: OAuth Direct + 4단 캐시

**제목**: subprocess 1번 안 띄워서 5초 벌었습니다

**핵심**:
- 보통 `claude-agent-sdk` → subprocess `claude` CLI spawn → **5-10초 overhead**
- 우리는 **OAuth Direct** — claude.ai team subscription 토큰을 빌려 Anthropic API 직접 호출
  - subprocess 우회 → fast track 5-8초 가능
  - 추가 과금 X (subscription quota만 소모)

**4단 캐시**:
1. File cache (raw parquet)
2. Preprocessed DataFrame cache (KST 보정 · action_type 정규화 완료)
3. Result-level cache (같은 도메인×기간 → dict 반환)
4. DB cache (`kpi_summary_cache`)

**+ 키워드 사전 분류** — 명확한 질문은 Gateway LLM도 skip → 13초 추가 절약

---

### 📄 슬라이드 9 — Iron Rule + PANDA 답변

**제목**: 신뢰도를 강제하는 가드레일

**Iron Rules** (코드 레벨 enforce):
- 도메인 격리: pedia가 adult 데이터 못 봄
- Bash 1번 룰: 정찰용 `ls / head / dtype` 금지
- cost cap **$3 / 세션**
- KST 자동 보정 (unix ts → +9h)
- **💡 인사이트 의무**: 모든 답변에 1-2줄 인사이트 강제

**PANDA 답변 형식** (Toss PANDA 영감):
1. 질문 요약 1줄
2. 표 / 차트 (Toss PANDA / NYT / Datawrapper 톤매너)
3. 집계 기준 명시
4. 💡 인사이트 1줄

**시각자료**: 실제 차트 한 장 (TOP1 강조 색 `#d97757` + 나머지 회색 `#e8e6dc`)

---

### 📄 슬라이드 10 — 앞으로

**제목**: 여기서 끝이 아닙니다

**Phase 로드맵**:
- **Phase 2**: Domain Expert Subagent 4명 (코드는 `agents/domain_experts.py`에 ready, 사내 데이터 권한 대기 중)
- **Phase 3**: Reviewer Subagent — 답변을 trivial / duplicate / jargon / offtopic 4축으로 검증
- **Phase 4**: Semantic Cache (pgvector) + 사내 노션 분석 자료 RAG

**비전**:
> "Toss panda가 사내 archive를 분석가 누구에게나 열어준 것처럼,
> 우리는 archive를 넘어 다양한 데이터 소스로 —
> **누구나 데이터 분석가가 되는 다리**를 만들고 있습니다."

**마무리 멘트**: "감사합니다. 질문 / 같이 써보고 싶은 분, 환영합니다."

---

## ✅ PPT 생성 prompt 작성 시 추가 고려사항

1. **톤**: ML 엔지니어 전문성 + 약간의 위트 (실패담 인정형)
2. **색감**: Watcha 톤매너 — 강조 `#d97757`, 보조 `#6a9bcc`, 배경 `#e8e6dc`
3. **폰트**: Pretendard
4. **다이어그램 도구**: Mermaid 또는 Excalidraw 스타일 깔끔하게
5. **코드 블록**: 슬라이드 7에 SYSTEM_PROMPT + Gateway prompt 실제 인용
6. **각 슬라이드 우측 하단**: 페이지 번호 + 작은 ☕ MOCHA 아이콘

---

## 📚 부록 — 발표 중 질문 대비 핵심 수치

| 항목 | 수치 |
|---|---|
| Gateway 응답 시간 | ~6초 (Sonnet 1턴) |
| Fast Track (narrow) | 16-21초 / ~$0.05 |
| Fast Track + KPI inline | 5-8초 / ~$0.01 |
| Slow Track (broad EDA) | 30-90초 / ~$0.3-0.7 |
| Slow Track (A/B test) | 60-120초 / ~$0.5-1.0 |
| Cost cap | $3 / 세션 |
| Full EDA 1회 실측 | ~$1.6 |
| 지원 도메인 | 4개 (galaxy / mars / adult / ml_1m) |
| Templates | 4개 |
| Skills | 6개 |

## 🔗 참고 링크 (PPT에 첨부)

- CAVEMAN 영감 GitHub 링크: `_______________________` (사용자 추가 예정)
- Toss PANDA 참고
- MOCHA Architecture: `ARCHITECTURE.md`
