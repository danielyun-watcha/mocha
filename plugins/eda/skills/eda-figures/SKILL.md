---
name: eda-figures
description: EDA 분석 결과 JSON을 받아 PPT 스타일 정적 PNG figures를 생성한다. 한국어 폰트·인사이트 박스·annotation을 자동 적용하며 분석 종류에 맞는 layout(stat_callout/pie/bar/boxplot/line/lorenz 등)을 선택한다. Use when 분석이 끝난 후 보고서·노션에 임베드할 그림이 필요할 때.
allowed-tools: Read, Write, Bash(python3 *), Bash(ls *), Bash(mkdir *), Bash(cp *)
argument-hint: <analysis_results.json> [output_dir] [--theme <name>]
disable-model-invocation: true
---

# EDA Figures

## Overview

분석 스킬(eda-overview / eda-action / eda-tail / eda-temporal 등)이 생성한 `analysis_results.json`을 받아, PPT 스타일 PNG figures (3~6장)를 생성한다. 차트 종류는 분석 결과의 신호에 따라 자동 선택되며, 한국어 폰트·인사이트 박스·annotation이 일관되게 적용된다.

## Workflow

### Step 0: 입력 확정

- 인자 1: `analysis_results.json` 경로 (필수)
- 인자 2: 출력 디렉토리 (선택, 기본 `./figures/`)
- `--theme <name>`: 테마 이름 (기본 `watcha-default`. 사용 가능 테마는 `themes/*.md`)
- `--brief <path>`: `eda-intake`가 생성한 `analysis_brief.json` (선택, 도메인/기간/제목에 활용)

### Step 1: Layout 선택 (분석 결과 신호 → layout 매핑)

`analysis_results.json` 구조를 확인하고 `references/layout_catalog.md`의 매핑 룰에 따라 각 섹션에 적절한 layout을 결정한다. 핵심 매핑:

| 분석 결과 키 | 권장 layout |
|---|---|
| `overview` (단일 수치 모음) | `stat_callout` |
| `content_type` (2~5 카테고리 비율) | `pie_chart` |
| `value_boxplot` 또는 `*_boxplot` (quartile 있음) | `boxplot` (분포 범위 크면 log scale) |
| `daily_volume` 또는 `monthly_volume` (시계열) | `line_chart` (+ 7일 이동평균) |
| `lorenz` 또는 `pareto_long_tail` (누적) | `lorenz_curve` |
| `value_buckets_pct` (구간 분포) | `bar_chart` |
| `*_buckets` + `*_boxplot` (분포 + summary) | `bar + boxplot 2-panel` |
| `venn_*` (집합 겹침) | `venn_overlap` |
| `*_100people` (100명/100개 인포그래픽) | `people_grid` |

후보가 모호하면 한 분석 결과에 여러 layout 시도 가능. 자세한 결정 규칙은 `references/layout_catalog.md` 참조.

### Step 2: 렌더링 실행

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/render.py \
    <analysis_results.json> \
    --output <output_dir> \
    --theme <theme_name>
```

`render.py`는 다음을 수행:
1. 테마 로드 (`themes/<name>.md`에서 색·폰트 파싱)
2. 한글 폰트 setup (`assets/fonts/` 폴백)
3. plt.rcParams 통일 (`references/design_principles.md`의 8개 원칙 적용)
4. 각 layout 모듈 호출 (`scripts/layouts/<name>.py`)
5. `output_dir/F1_*.png ... FN_*.png` 저장 (240 DPI)

### Step 3: 결과 확인 및 보고

생성된 figure 목록을 사용자에게 보여준다:
```
생성된 figures:
  F1_overview.png      (stat_callout — 데이터셋 개요)
  F2_content_type.png  (pie + boxplot — 카테고리 비율 + 분포)
  ...
```

`output_dir`을 다음 스킬(`eda-report`, `notion-publish`)이 참조할 수 있도록 안내한다.

## Design Principles (요약)

자세한 원칙은 `references/design_principles.md`. 핵심:

1. **Non-data ink 최소화** (spine 제거, grid alpha 0.3)
2. **annotate() + 화살표**로 peak/anomaly 직접 표시
3. **인사이트 박스** 모든 figure에 1개 (`fff3e0` 배경, `f57c00` 테두리)
4. **3-tier 색상** (dark/light/neutral) + **3-accent 순환**
5. **한글 폰트 폴백** NotoSansKR → Malgun → DejaVu (`references/font_setup.md`)
6. **DPI 240+** PNG 출력 (보고서·노션 임베드용)
7. **모든 figure는 시각 요소 + 텍스트 박스 균형**
8. **분석 결과 종류에 맞는 차트 선택** (bar만 X — pie/box/line/CDF 등)

## Resources

### scripts/

- **`scripts/render.py`**: 메인 진입점 (analysis_results.json + theme → PNG). 위 Step 2에서 호출.
- **`scripts/layouts/__init__.py`**: layout 모듈 패키지 진입점.
- **`scripts/layouts/_common.py`**: 모든 layout이 공유하는 helper (insight_box, clean_spines, accent_cycle).
- **`scripts/layouts/stat_callout.py`**: 큰 숫자 모음 layout.
- **`scripts/layouts/pie_chart.py`**: 2~5 카테고리 비율 layout.
- **`scripts/layouts/bar_chart.py`**: 범주형 / 구간 분포 layout.
- **`scripts/layouts/boxplot.py`**: quartile 분포 비교 layout.
- **`scripts/layouts/line_chart.py`**: 시계열 + 이동평균 layout.
- **`scripts/layouts/lorenz_curve.py`**: 누적 점유 (Pareto) layout.
- **`scripts/layouts/bar_box_2panel.py`**: 분포 막대 + summary boxplot 결합 layout.
- **`scripts/layouts/venn_overlap.py`**: 2~3 set 겹침 layout (matplotlib_venn 필요).
- **`scripts/layouts/people_grid.py`**: 100명/100개 인포그래픽 layout.

### references/

- **`references/design_principles.md`**: 8개 디자인 원칙 (Non-data ink, annotation, 인사이트 박스 등).
- **`references/layout_catalog.md`**: 분석 결과 키 → layout 매핑 룰 (`select_layout()`의 근거).
- **`references/theme_spec.md`**: 테마 파일 형식 (`themes/<name>.md` 작성 가이드).
- **`references/font_setup.md`**: 한글 폰트 폴백 체인 + 이모지 글리프 주의.

### themes/

- **`themes/watcha-default.md`**: 기본 테마 (라이트 + 친화적 + 한국어).

### assets/

- **`assets/fonts/malgun.ttf`**: 한글 폰트 fallback (Windows Malgun Gothic).
