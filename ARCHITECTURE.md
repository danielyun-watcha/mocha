# MOCHA Architecture

> Watcha 사내 데이터 분석 AI 어시스턴트. claude-agent-sdk 기반 single-agent (Phase 1) → domain expert subagent (Phase 2) 확장 구조.

## 핵심 다이어그램

```
사용자 질문 (chat UI)
        ↓
┌──────────────────────────────────────────────────────────┐
│  MOCHA (FastAPI + claude-agent-sdk)                      │
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │  🚦 Gateway (Sonnet, 1턴, ~6초)                   │  │
│  │  JSON 분류:                                        │  │
│  │   ├─ track:   fast | deep                         │  │
│  │   ├─ intent:  narrow_top_n | broad_eda | ab_test  │  │
│  │   │           | report | interpretive_qa | ...     │  │
│  │   ├─ domain:  ml_1m | watcha_main | adult         │  │
│  │   │           | pedia | unknown                    │  │
│  │   └─ summary: 한 줄 요약                           │  │
│  └────────────────────────────────────────────────────┘  │
│            ↓                              ↓               │
│  ┌──────────────────────┐    ┌──────────────────────┐    │
│  │  🏎️ Fast Track       │    │  🐢 Deep Track       │    │
│  │  ──────────────       │    │  ──────────────       │    │
│  │  단일 Lead (Sonnet)  │    │  Phase 1: 단일 Lead   │    │
│  │  SYSTEM_PROMPT 의    │    │  Phase 2: Domain      │    │
│  │  도메인 표 + 격리룰  │    │  Expert spawn         │    │
│  │  ↓                   │    │   ├─ watcha-main-expert│    │
│  │  Bash 1-2회          │    │   ├─ adult-expert     │    │
│  │  + Read 템플릿       │    │   ├─ pedia-expert     │    │
│  │  + 답변              │    │   └─ ml-1m-expert     │    │
│  │  ⏱️ ~10-20초         │    │  ⏱️ ~30-90초          │    │
│  └──────────────────────┘    └──────────────────────┘    │
│            ↓                              ↓               │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Knowledge Assets (모든 track 공유)                │  │
│  │   ├─ 6 Skills — eda-overview/figures/casestudy/   │  │
│  │   │           report/intake/notion-publish        │  │
│  │   ├─ 4 Templates — light_memo/full_eda/ab_test/   │  │
│  │   │              analysis_report                  │  │
│  │   └─ Guardrails — KST 보정 · 도메인 격리 · 인사이트│  │
│  │                  필수 · cost cap $3                │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
        ↓
사용자 답변 (PANDA 형식 + 💡 인사이트)
```

## 4-Layer Cognitive Architecture (발표용 서사)

단일 Lead 의 동작을 4 layer 로 분해해 컨셉화:

| Layer | 역할 | 구현 |
|---|---|---|
| **Layer 1: Intent Router** | track / intent / domain 분류 | Gateway (Sonnet, 1턴) |
| **Layer 2: Planning** | tool/skill 선택, 데이터 경로 결정 | Lead 의 SYSTEM_PROMPT + 도메인 표 |
| **Layer 3: Execution** | pandas/matplotlib 실행 + sub-skill 호출 | Lead 의 Bash + Skill tool |
| **Layer 4: Output Synthesis** | 템플릿 채우기 + 인사이트 작성 | Lead 의 Read templates + Write |

각 layer 가 정해진 페르소나 (Senior Analyst / Method Selector / Code Executor + Domain Expert / Report Writer) 를 한 명이 동시에 수행.

## Gateway 분류 룰

| Intent | Track | 처리 |
|---|---|---|
| `narrow_top_n` · `narrow_distribution` · `narrow_count` | fast | Bash 1회 pandas 직접 |
| `interpretive_qa` (큰손/장르 등) | fast | cache or pandas |
| `notion` · `small_talk` | fast | skill 또는 직접 |
| `broad_eda` · `ab_test` · `report` | deep | (Phase 1) Lead 단일 / (Phase 2) Domain Expert |

## 도메인 격리 (Iron Rule)

| Domain | 전용 archive scope | 공유 archive |
|---|---|---|
| `ml_1m` | `data/rating_prediction/ml-1m/` | — |
| `watcha_main` (mars) | `/archive/graph_modeling/` · `next_watch/` · `next_purchase/` · `user_bert/` | `/archive/rating_prediction/` |
| `adult` (rec_adult) | `/archive/rec_adult/` · `next_adult/` · `user_bert_adult/` · `adult_foundation/` | — |
| `pedia` (rec_galaxy) | `/archive/rec_galaxy/` | `/archive/rating_prediction/` |
| `unknown` | — (사용자 확인 필요) | — |

**격리 보장 메커니즘**:
- Phase 1: SYSTEM_PROMPT 의 도메인 표 + Iron rule instructions
- Phase 2: Domain Expert AgentDefinition 의 별도 SYSTEM_PROMPT 로 코드 레벨 격리

**Sub-path 결정** (예: `rec_adult/builtin/` vs `behavior_logs/` vs `exp-*/`):
1. 사용자 질문 키워드 (원본/실험/기본)
2. `eda-intake/scripts/probe_data.py` 호출 → sibling 분류
3. 후보 ≥ 2 → `AskUserQuestion` 1회

## Skills (Standalone)

각 skill 은 독립 호출 가능. Lead 가 의도 보고 선택:

| Skill | 책임 | 입력 | 출력 |
|---|---|---|---|
| `eda-overview` | 기본 통계 / sparsity / 시간 / Pareto / 분포 | `<data_path>` | `analysis_results.json` |
| `eda-casestudy` | TOP10 사례 (큰손/충성 콘텐츠/헤비 rater) | `<data_path>` | `case_studies` 키 |
| `eda-figures` | PPT-style PNG figures (themed) | json 또는 raw + 자연어 | `/tmp/eda/*.png` |
| `eda-report` | Korean Markdown 리포트 (full/Q&A) | json + figures dir | `EDA_REPORT.md` |
| `eda-intake` | 대화형 brief 생성 + archive 매핑 | (자연어) | `analysis_brief.json` |
| `notion-publish` | MD → Notion 새 페이지 | MD 파일 | Notion URL |

## Templates (답변 양식)

`plugins/eda/templates/` 에 4개. Lead 가 의도 보고 Read 후 채움:

| Template | 사용 케이스 | 분량 |
|---|---|---|
| `01_light_memo.md` | TOP N · 분포 · 단순 통계 + 인사이트 1-2개 | 30-50줄 |
| `02_full_eda.md` | EDA · 데이터 특성 (성인+/galaxy 자료 모방) | 150-300줄 |
| `03_ab_test.md` | A/B test 사후 (Rec Adult Diff 모방, DID + 헤비유저 분리) | 200-400줄 |
| `04_analysis_report.md` | 분석 노트 (사용자 메모 양식) | 100-200줄 |

## Guardrails

- **cost cap**: `max_budget_usd=$3` per session (claude-agent-sdk `ResultMessage(subtype="error_max_budget_usd")` 분기)
- **KST 보정**: `updated_at` 같은 unix ts 는 UTC + 9h
- **인사이트 의무**: 모든 답변에 💡 인사이트 1-2개 (Toss PANDA + 사용자 EDA 자료의 "시사점" 컬럼 패턴)
- **도메인 격리**: Iron rule (위 표)
- **Bash 1회 단일 블록**: 정찰 ls/find 금지 (속도 + 비용)
- **시각화**: inline `![](/eda-files/X.png)`, 차트 1개당 파일 1개, vertical 막대, NanumGothic 한글 폰트

## 자산 구조

```
mocha/
├── main.py                          # FastAPI + Gateway + Lead
├── agents/
│   ├── __init__.py
│   └── domain_experts.py            # Phase 2 부활용 (현재 비활성)
├── plugins/eda/
│   ├── skills/                      # 6 sub-skills (각 standalone)
│   │   ├── eda-overview/
│   │   ├── eda-casestudy/
│   │   ├── eda-figures/
│   │   ├── eda-report/
│   │   ├── eda-intake/              # archive_map.md · probe_data.py
│   │   └── notion-publish/
│   ├── templates/                   # 4 답변 양식
│   │   ├── 01_light_memo.md
│   │   ├── 02_full_eda.md
│   │   ├── 03_ab_test.md
│   │   ├── 04_analysis_report.md
│   │   └── README.md
│   └── .archived/                   # 비활성 자산 (Phase 0/1 의 multi-agent)
│       ├── eda-orchestrator-2026-05-21/
│       └── agents-multiagent-2026-05-21.py
├── data/                            # 워크스페이스 로컬 (ml-1m 등)
└── static/                          # 채팅 UI (vanilla HTML/JS)
```

## Phase 로드맵

| Phase | 시점 | 변경 |
|---|---|---|
| **Phase 0** | 2026-05-20 초기 | Single Lead + 6 skills + multi-agent fan-out (over-engineering 으로 archive 처리) |
| **Phase 1** ✓ | 2026-05-20 ~ 21 | Single Lead + Gateway + 4 templates + 도메인 격리 instructions |
| **Phase 2** | 사내 데이터 권한 확정 시 | Deep track 에 Domain Expert Subagent 4명 spawn (`agents/domain_experts.py` 활성화) |
| **Phase 3** | 검토 후 | (옵션) Reviewer Subagent — deep 답변 4축 검증 (trivial/duplicate/jargon/offtopic) |
| **Phase 4** | 다음 | Semantic Cache (pgvector) + 사용자 노션 분석 자료 RAG |

## 비용·속도 측정 (Phase 1 기준)

| Track | 평균 시간 | 평균 비용 | tool calls |
|---|---|---|---|
| Fast (narrow) | 16-21초 | ~$0.05 | 2-3 |
| Fast (interpretive) | 20-30초 | ~$0.10 | 3-5 |
| Deep (broad EDA) | 30-90초 | ~$0.3-0.7 | 5-10 |
| Deep (A/B test) | 60-120초 | ~$0.5-1.0 | 7-15 |

Gateway 자체 ~6초 / $0.005 (모든 track 공통, Sonnet 1턴).
