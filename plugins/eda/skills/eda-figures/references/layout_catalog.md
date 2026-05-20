# Layout Catalog — 분석 결과 → 차트 매핑

`analysis_results.json`의 키와 값 형태를 보고 적절한 layout을 선택한다. agent가 자동으로 매핑할 수 있도록 규칙을 명시.

## 9개 Layout

### 1. `stat_callout` — 큰 숫자 모음

**언제**: 데이터셋 개요. 단일 수치 3~6개로 압축.

**입력 신호**:
```json
"overview": {
  "n_rows": 2329797, "n_users": 142181, "n_contents": 14425,
  "rows_per_user_mean": 16.39, "span_days": 119,
  "date_range": ["2026-01-13", "2026-05-12"]
}
```

**렌더링**: 4개 big number (40pt+) + 부제 (12~14pt) + 인사이트 박스. 막대/차트 없음.

### 2. `pie_chart` — 카테고리 비율

**언제**: 2~5 카테고리의 비율 (movie vs series, action 종류 등).

**입력 신호**:
```json
"content_type": {"movie_pct": 43.56, "series_pct": 56.44}
```
또는 임의 카테고리 dict `{"label": pct, ...}` 형태로 4개 이하.

**렌더링**: pie + `autopct="%1.1f%%"` + 흰색 wedge border + 라벨 외부.

### 3. `bar_chart` — 범주형 비교 / 구간 분포

**언제**: 5~10 카테고리의 수치 비교 또는 구간 분포 (value buckets, level buckets).

**입력 신호**:
```json
"value_buckets_pct": {"5-10": 4.95, "10-50": 15.97, "50-100": 7.55, "100+": 71.52}
```

**렌더링**: vertical bar + label 위에 % + annotation 화살표 (강조 구간). 5개 이하면 wide bar.

### 4. `boxplot` — 분포 비교

**언제**: 2개+ 그룹의 분포(quartile) 비교. 분포 범위가 크면 log scale.

**입력 신호** (`*_boxplot` 키):
```json
"value_boxplot": {
  "movie":  {"p5": 8, "q1": 33, "median": 185, "q3": 571, "p95": 2000},
  "series": {"p5": 16, "q1": 201, "median": 821, "q3": 1708, "p95": 4500}
}
```

**렌더링**: `ax.bxp()` patch_artist + 중앙값을 박스 옆 별도 annotation (혼동 방지). max/min p95 차이가 100배+ 면 `set_yscale("log")`.

### 5. `line_chart` — 시계열

**언제**: 시계열 데이터 (daily/weekly/monthly volume). 시간 trend 시각화.

**입력 신호**:
```json
"daily_volume": {"2026-01-13": 16585, "2026-01-14": 18234, ...}
```
또는 `"monthly_volume": {...}`.

**렌더링**: line + fill_between + **7일 이동평균** (data point ≥ 14일이면). x-axis ticks는 매월 1일.

### 6. `lorenz_curve` — 누적 분포 (long-tail / Pareto)

**언제**: 누적 점유율 시각화. Pareto 법칙 검증.

**입력 신호**:
```json
"lorenz": {"x_pct": [1, 2, ...], "y_pct": [15, 28, ...]},
"pareto_long_tail": {"top1pct": 15.38, "top5pct": 40.5, ...}
```

**렌더링**: line + fill_between + 균등 분포 reference line (점선) + key point scatter (top 1%/5%/10%/20%) + annotation.

### 7. `bar_box_2panel` — 분포 + 통계 요약

**언제**: 분포 막대와 quartile 박스를 함께 보고 싶을 때 (유저 활동 등). cap/임계점 강조.

**입력 신호**:
```json
"user_activity_buckets": {"2~5": ..., "6~10": ..., ...},
"user_activity_boxplot": {"q1": 6, "median": 11, "q3": 22, "max": 49}
```

**렌더링**: GridSpec width_ratios=[2, 1]. 왼쪽 bar, 오른쪽 boxplot. boxplot에 `max=49 (cap)` 같은 annotation.

### 8. `venn_overlap` — 집합 겹침

**언제**: 2~3개 집합의 교집합/차집합 (신호 간 overlap, 유저 그룹).

**입력 신호**:
```json
"venn": {
  "set_a_only": 11913, "set_b_only": 44723, "intersection_ab": 15277,
  ...
}
```

**렌더링**: `matplotlib_venn.venn2()` 또는 `venn3()`. 색은 3-accent + alpha 0.55.

### 9. `people_grid` — 100명/100개 인포그래픽

**언제**: 카테고리 분류를 100명/100개 그리드로 시각화. 직관적 비유.

**입력 신호**: 카테고리 비율 데이터 (합 = 100% 또는 사용자 정의 normalize).

**렌더링**: 10x10 Rectangle 그리드. 카테고리별 색 분리. 2x2 legend.

---

## 매핑 결정 트리

```
analysis_results.json 키 확인:

├── overview                        → F1 stat_callout
├── content_type / *_dist 2~5 cat   → pie_chart
├── *_buckets (5~10 범주형)         → bar_chart
├── *_boxplot                       → boxplot
│     └── 함께 *_buckets 있으면      → bar_box_2panel
├── daily_volume / monthly_volume   → line_chart
├── lorenz / pareto_*               → lorenz_curve
├── venn_*                          → venn_overlap
└── *_100people / *_grid            → people_grid
```

여러 키가 있으면 각 분석 결과마다 하나의 figure 생성. 한 figure에 6개 분석 결과를 다 담지 말 것 (인지 부하).

## 보고서 figure 권장 수

- 최소 3개 (Executive Summary + 핵심 발견 2~3개)
- 최대 6개 (보통 보고서 한 섹션당 1개)
- 6개 초과 시 → 핵심 인사이트 위주로 다시 추리기. "이 figure가 없어도 보고서가 통하는가?" 점검.
