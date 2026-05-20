---
name: eda-overview
description: 데이터셋 개요 + 시간 트렌드 + Long-tail + 주요 변수 분포 + 데이터 품질을 한 번에 분석한다. RecSys 표준 지표(sparsity/density/interactions per user)를 자동 계산하며, 분석 결과를 analysis_results.json에 추가한다. Use when EDA의 첫 단계로 데이터 전반 특성을 파악할 때.
allowed-tools: Read, Write, Bash(python3 *), Bash(ls *)
argument-hint: <data_path> [--brief <brief.json>] [--out <analysis_results.json>] [--append]
disable-model-invocation: true
---

# EDA Overview

## Overview

데이터셋 전반 특성을 한 번에 분석하는 스킬. RecSys 표준 지표(sparsity, interactions per user/item)와 시간 트렌드, long-tail, 데이터 품질을 자동 계산한다. 분석 결과를 `analysis_results.json`에 추가하며, 이후 `eda-figures`가 이걸 읽어 PPT-style 그림을 자동 생성한다.

## Workflow

### Step 0: 입력 확인

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/run.py <data_path> \
    [--brief <brief.json>] \
    [--out ./analysis_results.json] \
    [--append]
```

- `data_path`: 분석할 데이터 디렉토리 (예: `/archive/graph_modeling/builtin`)
- `--brief`: `eda-intake`가 생성한 `analysis_brief.json` (도메인 메모/기간 힌트)
- `--out`: 결과 저장 경로 (기본 `./analysis_results.json`)
- `--append`: 기존 파일에 자기 섹션만 병합 (다른 분석 스킬 결과 보존)

### Step 1: 도메인 감지 + Main file/column 결정

`references/domain_mapping.md`의 매핑 룰을 참조해 도메인을 식별하고 main 파일·컬럼을 자동 선택:

| 경로 패턴 | Main file | Main numeric col | Type 컬럼 |
|---|---|---|---|
| `graph_modeling/builtin` or `exp-*` | `train.ftr` | `value` (시청률) | `content_type` (Movie/Series) |
| `rec_galaxy/*` | `train.ftr` | `value` | `content_type` (멀티) |
| `rec_adult/*` | `adults.ftr` | `value` | **없음** (Movie만) |
| `rating_prediction/*` | `ratings.ftr` | `value` (1~10 평점) | 없음 |
| `next_*/*` | `train` 또는 `watch_logs.ftr` | `value` | 도메인별 |
| `behavior_logs/*` | 가장 최근 `.ftr` | 자동 탐지 | 도메인별 |

매핑 안 되면 `AskUserQuestion`으로 확인 (또는 `--brief`에서 hint).

### Step 2: 6개 분석 모듈 실행

`scripts/analyses/` 안 6개 모듈을 순차 실행 (각자 자기 키만 JSON에 추가):

| 모듈 | 출력 키 | 내용 |
|---|---|---|
| `overview.py` | `overview` | n_rows/users/contents, **sparsity/density**, interactions per user/item (mean/median), 기간 |
| `temporal.py` | `daily_volume`, `monthly_volume` | 일별/월별 시청량 |
| `tail.py` | `lorenz`, `pareto_long_tail` | Lorenz 곡선 + Top k% 점유율 |
| `content.py` | `content_type` (단일 타입 도메인은 skip) | Movie/Series/Book/Webtoon 비율 |
| `value_dist.py` | `value_buckets_pct`, `value_describe` | 평점/시청률 구간 분포 + 통계량 |
| `quality.py` | `data_quality` | null 비율, 중복 수, value outlier (figure 없음, 텍스트만) |

### Step 3: JSON 저장

`--append` 모드면 기존 파일 읽어서 이 스킬의 키만 덮어쓰기 (다른 키 보존). 아니면 새로 저장.

### Step 4: 결과 보고

```
Saved to ./analysis_results.json (overwrote 6 sections)
Key findings:
  - 142K users · 14.4K contents · 2.33M interactions (sparsity 99.89%)
  - 일별 시청량: 1월 평균 9.9K → 4월 평균 21.1K (+113%)
  - Long-tail: 상위 5% 콘텐츠가 시청의 40.5% 점유
  - value 중앙값 501 (영화 185, 시리즈 821)
다음 단계: /eda-figures ./analysis_results.json
```

## RecSys 핵심 지표 (overview)

학술 논문 dataset 섹션 표준:

- **sparsity** = `1 - n_rows / (n_users × n_items)` — 95% 이하면 학습 용이, 99%+ 면 cold-start 도전
- **mean interactions per user** — 데이터 풍부도
- **mean interactions per item** — popularity 균등도

## 도메인 적응

- **단일 타입 도메인** (adult, rating_prediction): `content` 섹션 자동 skip
- **type 컬럼 없는 도메인**: `content_type` 키 안 만듦
- **시간 정보 없는 도메인**: `temporal` 섹션 skip

## Resources

- **`scripts/run.py`**: 메인 진입점 (인자 파싱 + 도메인 매핑 + 6 모듈 dispatch)
- **`scripts/analyses/overview.py`**: 기본 통계 + sparsity/density
- **`scripts/analyses/temporal.py`**: 일별/월별 시청량
- **`scripts/analyses/tail.py`**: Lorenz + Pareto top k%
- **`scripts/analyses/content.py`**: 콘텐츠 타입 분포 (도메인 적응)
- **`scripts/analyses/value_dist.py`**: Main numeric 분포 (평점/시청률 등)
- **`scripts/analyses/quality.py`**: null/중복/outlier 점검
- **`scripts/analyses/cross.py`**: cross-tab 분석 (content_type × value, 유저 segment, 시간대 × type)
- **`scripts/analyses/_common.py`**: 데이터 로드 + 도메인 매핑 helper + KST 보정 timestamp
- **`scripts/analyses/__init__.py`**: analyses 패키지 진입점
- **`references/domain_mapping.md`**: 도메인 → main file/column 매핑 사전
