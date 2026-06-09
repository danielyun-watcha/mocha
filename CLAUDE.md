# MOCHA — Claude Code guide

자연어로 묻는 Watcha 데이터 분석 AI. `main.py`(FastAPI + claude-agent-sdk) +
`kpi.py`(집계) + `data_sources/`(I/O) + `semantic/`(용어·지표 메타) + `plugins/eda`.

## 데이터 소스 우선순위 — **archive-first, BQ-fallback**

```
1순위: /archive/*  (NFS feather) — 빠름, 비용 0, 사전집계
2순위: archive 에 없으면 → BigQuery (gretel.*, pacific-350708.*) 탐색
```

분석/질문 처리 시 **항상 archive 를 먼저** 본다. archive 에 해당 데이터(도메인·
기간·액션)가 있으면 BQ 를 호출하지 않는다. 없을 때만 BQ. (ADP 파드는 BQ 읽기
권한 보유 — IRSA/WIF 자동 주입.)

## /archive 카탈로그 (mocha 가 읽는 것)

데이터 범위는 런타임에 `kpi.available_range(domain)` 으로 확인 (파일명
`YYYYMMDD_YYYYMMDD.ftr` 기반). 아래는 2026-06 기준 스냅샷 — **갱신은 prepare
cron 이 하므로 실범위는 코드로 확인할 것**.

| 도메인 | 경로 | 데이터 | 범위(2026-06 기준) | 액션 |
|---|---|---|---|---|
| **galaxy** (왓챠피디아) | `/archive/rec_galaxy/behavior_logs/` | 행동 로그 | 2025-05-20 ~ **현재** | RATE/WISH/SEARCH/CLICK (int 1/2/6/7) |
| **mars** (왓챠) | `/archive/user_bert/behavior_logs2/train/` | 행동 로그 (월별 누적) | 2025-05-14 ~ **2026-05-14** ⚠️ | CLICK/PLAY/WISH/SEARCH/RATE `:MARS` (galaxy 이벤트 섞임 → `:MARS` 필터 필수) |
| **adult** (성인+) | `/archive/rec_adult/behavior_logs/` | 행동 로그 | 2024-08-25 ~ **현재** | click/preview/play/wish/rental/possession (소문자) |

### mocha 전용 archive (`/archive/mocha/`) — BQ 에서 dump 한 것

| 파일 | 내용 | 소스 | 비고 |
|---|---|---|---|
| `mehs.ftr` | MEH(관심없음) 풀 history 15.6M행 | BQ `gretel.frograms_us.mehs` | galaxy/mars 공통. `read_mehs()` |
| `mars_tvod_purchases.ftr` | mars TVOD 결제 1년치 791k행 | BQ `hudson_us.{rentals,possessions}+payments` | 매출/결제. `read_mars_tvod_purchases()` |
| `sessions/` | mocha chat export (output) | — | 분석에 쓰는 input 아님 |

### 보조 archive (특정 panel)

| 경로 | 용도 |
|---|---|
| `/archive/rating_prediction/default/ratings.ftr` | RATE 전체 history (5GB, filter 없는 1-10 raw). 정밀 평점 분석용 |
| `/archive/graph_modeling/builtin/` | 인기 배우·감독(credit edges) + genre map. `_load_graph_meta`/`_load_genre_map` |
| `/archive/foundation_tmp/items/{type}/meta.parquet` | content_id → 장르명 |
| `_runtime/content_titles_ko.pkl` | content_id → 한국어 제목 (MySQL 유래, `scripts/expand_title_map.py` 로 생성) |

## ⚠️ 데이터 신선도 caveat

- **mars 는 ~3주 stale** (현재 2026-05-14 까지) — galaxy/adult 는 당일. mars 최근
  데이터 질문 시 "최신 ~2026-05-14 기준" 명시. 더 최신 필요 시 BQ
  (`remy_mars` / `mars_play_log_video`).
- archive 에 **없는** 것 → BQ 직행: country 필터(archive 에 country 없음), 실시간
  당일 데이터, MEH 외 신규 액션 등.

## 데이터 경로 (분석 시 빠른 판단 순서)

1. 질문의 도메인·기간·액션 파악 → **archive 범위 안인가?** (`available_range`)
2. archive 안이면 `kpi.summary_fast` / `kpi.top_items` (DuckDB, 빠름)
3. archive 밖(country/실시간/미적재)이면 BQ — `data_sources/bq.py` fetcher + `estimate_cost` dry-run 먼저

## 실행

```bash
IS_SANDBOX=1 DEV_PORT=8090 python3 _runtime/launch.py
```
- **archive 경로는 자동 해석** (`data_sources/_archive_root.py`): `ARCHIVE_DIR` 환경변수 →
  없으면 marker(rec_galaxy/rec_adult/tutorial) 있는 `/archive` → `/mnt/ml-archive` 순.
  즉 `/archive` 마운트만 돼 있으면 env·symlink 없이 동작. 강제 지정 시 `ARCHIVE_DIR=...`.
- `IS_SANDBOX=1` 필수 — root 환경에서 claude-agent-sdk 의 `--dangerously-skip-permissions` 거부 회피 (deep track 동작)

## 테스트 / 린트

```bash
pytest tests/          # archive 있으면 동일성 테스트까지 (없으면 skip)
ruff check .
```
- `tests/test_summary_fast.py`: summary_fast(DuckDB) ≡ summary(pandas oracle) 동일성
- 새 KPI/panel 추가 시 oracle 동일성 테스트 먼저 (TDD)

## 성능 메모

- 큰 윈도우 집계는 **DuckDB columnar** (`summary_fast`/`top_items`) — pandas 행처리
  금지 (mars 1년 790s → ~5-14s). feather 는 병렬 read(ThreadPoolExecutor).
- `summary()` 는 필터 없으면 `summary_fast` 로 위임, 실패 시 pandas fallback.
