---
name: eda-report
allowed-tools: Read, Write, Bash(python3 *)
argument-hint: <results_json> [--mode full|qa] [--question "..."] [--figures-dir <path>] [--out <path>]
disable-model-invocation: true
description: analysis_results.json + figures를 받아 Korean Markdown 리포트로 변환한다. 풀 리포트(전체 EDA 산출물) + Q&A(개별 질문 답변) 듀얼 모드 지원. PANDA 답변구조(헤더 / 결과 표 / 집계 기준 / 인사이트 / Appendix) 적용. Use when 분석 결과 JSON을 한글 리포트로 변환하거나 누적된 결과에 대해 자연어 질문에 답할 때.
---

# EDA Report Writer

`analysis_results.json` (eda-overview + eda-casestudy가 누적 생성한 JSON) 과 figures 디렉토리를 입력으로 받아 **Korean Markdown 리포트** 를 생성한다. Notion paste-ready.

## 듀얼 모드

| 모드 | 트리거 | 산출물 |
|---|---|---|
| **full** | 풀 EDA 마지막 단계 | 전체 리포트 (헤더 / 개요 / 시간·꼬리 / 집계기준 / 인사이트 / Appendix) |
| **qa** | "큰손이 누구야?" 같은 개별 질문 | 질문 의도에 맞는 표 1-2개 + 집계 기준 + 인사이트 3-5개 |

## 5단 답변 구조 (PANDA 템플릿)

```
[헤더]           질문 echo + 도메인 + 분석 일시
[결과 본체]      📅 표(들) — 핵심 데이터 우선
[집계 기준]      📊 기간 / 기준(정의) / 해석(용어)
[인사이트]       💡 결론 + 부연 + 해석 3단
[Appendix]      case_studies 표 (full 모드만)
```

수치는 항상 비교 맥락 포함. 표가 본문보다 우선. 이모지로 섹션 시각 구분.

---

## 워크플로

### Mode A: 풀 리포트

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/render_full_report.py \
    <results_json> \
    --figures-dir <figures_dir> \
    --out <output_md>
```

1. `_meta` 블록에서 도메인/기간/n_rows 추출 → 헤더 + 집계 기준
2. `overview` / `daily_volume` / `lorenz` / `pareto_long_tail` → §개요 + §시간·꼬리
3. figures 디렉토리 스캔 → MD 이미지 임베드
4. `case_studies` → §Appendix 표
5. `analysis_suggestions` → §인사이트 (3단 구조 슬롯 생성)

생성된 MD의 **§인사이트 슬롯**을 Claude가 한 번 더 다듬는다 (결론 한 줄 → bullet 부연 → 해석 코멘트). 표·수치는 Python이 박은 그대로 유지.

### Mode B: Q&A

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/render_qa.py \
    <results_json> \
    --question "<자연어 질문>" \
    --out <output_md>
```

1. 질문 키워드 매칭 → 관련 섹션(`heavy_users` / `loyal_content` / `sparsity` 등) 추출
2. 위 5단 구조 한 번만 — Appendix 없음, 표 1-2개로 압축
3. 결과 MD 출력 또는 STDOUT.

질문 라우팅 가이드: `references/qa_routing.md`

---

## 인사이트 3단 구조 (모든 모드 공통)

```markdown
✅ **{한 줄 결론}**
- {수치 부연 1}
- {수치 부연 2 — 비교 맥락 포함}
- {해석/암시 — "이는 X로 해석됨"}
```

Python이 `analysis_suggestions`의 한 줄 문장을 그대로 결론으로 옮기고, 부연/해석은 빈 슬롯으로 둔다. Claude가 JSON 컨텍스트(overview/case_studies)를 보고 부연·해석 라인을 채운다.

---

## Resources

### Scripts

- `scripts/render_full_report.py` — 풀 리포트 메인 엔트리
- `scripts/render_qa.py` — Q&A 메인 엔트리
- `scripts/sections/__init__.py` — 섹션 패키지 마커
- `scripts/sections/_common.py` — `_meta` 추출, 표 포맷팅 헬퍼
- `scripts/sections/header.py` — 헤더 블록
- `scripts/sections/tldr.py` — ⚡ 핵심 요약 (3-5 bullet, 풀 리포트 맨 앞)
- `scripts/sections/criteria.py` — 집계 기준 블록
- `scripts/sections/overview_section.py` — 데이터 개요 표·문장
- `scripts/sections/temporal_tail.py` — 시간/꼬리 분포 섹션 (legacy)
- `scripts/sections/distributions.py` — 시간·꼬리·시간대·Value 분포 (그림 + 도메인 설명)
- `scripts/sections/cross_analysis.py` — content_type × value cross-tab
- `scripts/sections/insights.py` — 추가 발견 및 권장 (deterministic 인사이트)
- `scripts/sections/deep_insight.py` — LLM 작성용 placeholder (오케스트레이터가 채움)
- `scripts/sections/appendix.py` — case_studies → MD 표
- `scripts/sections/_inspector_loader.py` — inspector 동적 로드 (render_full + render_qa 공유)

### References

- `references/report_structure.md` — 5단 구조 (조회기준→개요→분포→인사이트→Appendix)
- `references/qa_routing.md` — 질문 → 섹션 라우팅 표
- `references/llm_insight_pattern.md` — LLM Deep Insight 작성 가이드 (오케스트레이터가 따름)

---

## 입력 가정

- `_meta`: eda-overview가 자동 생성 (domain / data_path / main_file / period_start·end / n_days / generated_at)
- `overview`, `daily_volume`, `lorenz`, `pareto_long_tail`, `content_type`, `value_buckets_pct` 등: eda-overview 산출
- `case_studies`, `analysis_suggestions`: eda-casestudy 산출
- `figures-dir`: eda-figures가 생성한 PNG 디렉토리 (옵션)

누락 키는 해당 섹션을 자동 skip.
