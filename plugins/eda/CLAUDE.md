# EDA Plugin — Agentic Exploratory Data Analysis

Watcha 추천 시스템 데이터의 EDA(Exploratory Data Analysis)를 자동화하는 AI 에이전트 + skill 모음.

## 핵심 컨셉

PANDA-style 답변 + Plan-Generate-Evaluate ReAct 패턴. 자연어 질문 한 줄로 EDA 분석부터 Notion 업로드까지.

- **자연어 질문**: "큰손 유저는?", "장르 분석해줘", "graph_modeling EDA 리포트"
- **답변 구조**: 결과(표) + 집계 기준 + 인사이트 5개
- **시간대**: 모든 timestamp KST 자동 보정
- **Validator**: 결과 검증 + 부족 시 자동 재시도

## Skill 구성

| 스킬 | 역할 |
|---|---|
| `eda` | 오케스트레이터 — 자연어 → 의도 분류 → sub-skill 라우팅 + ReAct loop |
| `eda-intake` | 대화형 brief 생성 (데이터 경로 / 기간 / 목적) |
| `eda-overview` | 데이터 개요 + 시간 / 꼬리 / 품질 + cross-tab 분석 |
| `eda-casestudy` | TOP10 케이스 (heavy users / loyal content / peak hours …) |
| `eda-figures` | PNG 차트 자동 생성 (9 layout · 한글 폰트 · pastel 톤) |
| `eda-report` | Korean MD 리포트 (풀 + Q&A 듀얼 모드) · LLM Insight placeholder |
| `notion-publish` | MD → Notion 새 페이지 |

## 빠른 시작

```
/eda graph_modeling 데이터 분석해줘
/eda 큰손 유저가 누구야?
/eda 노션에 올려줘
```

## 사용 가능 도메인

`graph_modeling` / `next_watch` / `next_purchase` / `rec_galaxy` / `rec_adult` / `user_bert` / `rating_prediction`

각 도메인의 key_metric (play / buy / rate) 자동 매핑.

## 참고

- Toss PANDA · AWS Deep Insight (LG ChatInsight) · Self-Refine · DataSage 패턴 영감
- 상세 디자인: 별도 저장소 (`frograms/remy-worker-daniel` `eda-agent` 브랜치)
