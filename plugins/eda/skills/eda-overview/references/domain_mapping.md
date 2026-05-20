# Domain → Main file/column 매핑

`eda-overview/scripts/analyses/_common.py`의 `detect_domain()` 함수가 이 표를 따라 자동 분기.

## 매핑 표

| Path Pattern | Main File | Main Numeric Col | Type Column | 비고 |
|---|---|---|---|---|
| `graph_modeling/builtin` | `train.ftr` | `value` | `content_type` (1=Movie, 2=Series) | mars 왓고리즘 |
| `graph_modeling/exp-*` | `train.ftr` | `value` | `content_type` | 실험별 prep |
| `graph_modeling/behavior_logs/Svod` | `*.ftr` (가장 최근) | `value` | `content_type` | raw 시청 로그 |
| `rec_galaxy/builtin` | `train.ftr` | `value` | `content_type` (Movie/TV/Book/Webtoon) | galaxy 멀티 타입 |
| `rec_galaxy/exp-*` | `train.ftr` | `value` | `content_type` | |
| `rec_galaxy/behavior_logs` | `*.ftr` | `value` | `content_type` | raw |
| `rec_adult/builtin` | `adults.ftr` | `value` | **없음** | 성인+, Movie만 |
| `rec_adult/exp-*` | `train.ftr` 또는 `adults.ftr` | `value` | 없음 | |
| `rating_prediction/default` | `ratings.ftr` | `value` (1~10) | 없음 | 평점 원본 |
| `next_watch/default` | `watch_logs.ftr` 또는 train | `value` | `content_type` | mars 시청 시퀀스 |
| `next_purchase/default` | `train` | `value` | `content_type` | mars 구매 시퀀스 |
| `next_adult/exp-*` | `train` | `value` | 없음 | 성인+ 시퀀스 |

## 자동 감지 로직

```python
def detect_domain(data_path: Path) -> dict:
    """data_path → {main_file, main_value_col, type_col}"""
    parts = data_path.parts
    # 1. domain root 추출
    domain = next((p for p in parts if p in {
        "graph_modeling", "rec_galaxy", "rec_adult",
        "rating_prediction", "next_watch", "next_purchase",
        "next_adult", "user_bert", "user_bert_adult",
    }), None)

    # 2. main_file 결정
    candidates = ["train.ftr", "adults.ftr", "ratings.ftr",
                  "watch_logs.ftr", "valid.ftr", "test.ftr"]
    main_file = None
    for cand in candidates:
        if (data_path / cand).exists():
            main_file = cand
            break

    # 3. behavior_logs 케이스: 가장 최근 ftr 자동 선택
    if main_file is None:
        ftrs = sorted(data_path.glob("*.ftr"), key=lambda p: p.name)
        if ftrs:
            main_file = ftrs[-1].name

    # 4. type_col은 컬럼 존재 여부로 동적 판단 (단일 타입 도메인은 자동 skip)
    return {"domain": domain, "main_file": main_file,
            "main_value_col": "value", "type_col": "content_type"}
```

## 도메인별 의미 (보고서 라벨링)

| 도메인 | main_value_col의 의미 |
|---|---|
| mars (graph_modeling, next_watch) | `value = (시청 시간) × 10 / (콘텐츠 길이)` |
| galaxy (rec_galaxy) | `value` = 시청 누적 지수 (멀티 타입) |
| 평점 (rating_prediction) | `value = 1~10` (0.5★ 단위) |
| 성인+ (rec_adult, next_adult) | `value = 시청·구매 누적 또는 가격` |

## Type column이 단일 값일 때

`type_col`에 단일 값만 있으면 `content.py` 자동 skip. 예:
- rec_adult/adults.ftr: 모두 Movie → skip
- ratings.ftr: type 컬럼 없음 → skip
