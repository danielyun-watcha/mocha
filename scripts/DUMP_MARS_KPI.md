# Mars rec KPI archive dump

mocha 사이트의 **mars_adultplus / svod / tvod_all** dashboard 가 매번 BigQuery 를 스캔하는 것을 막기 위해, 1년치 데이터를 archive (NFS) 의 feather 파일로 미리 dump 해두는 1회용 스크립트입니다.

dump 후 mocha 사이트의 첫 진입 속도가 **~30s (BQ) → ~1-2s (feather)** 로 개선되고, daily BQ scan cost 가 **$0.05 → $0** 으로 떨어집니다.

---

## 1. 사전 요구사항

### 환경

- **Python 3.10+**
- **BQ 권한**: `ai-develop-platform` 또는 `gretel.production_us.remy_mars_kpi*` 테이블 read 권한
- **Archive write 권한**: `/archive/mocha/` (또는 `ARCHIVE_DIR` 환경변수 경로) 에 write 가능해야 함

### 추천 실행 환경

- **JupyterHub** (jupyter.watcha.com) — `/archive/` 가 rw 마운트, BQ ADC 자동 설정
- 또는 ADP pod 에서 IRSA 기반 BQ 권한 + archive write 가능한 환경

### 의존성 설치

```bash
pip install pandas pyarrow google-cloud-bigquery db-dtypes
```

(JupyterHub 기본 커널에는 이미 설치되어 있는 경우 많음)

---

## 2. 실행 방법

### 1년치 한 번에 (최초 1회, 권장)

```bash
# JupyterHub 터미널에서:
cd ~/mocha  # 또는 mocha 디렉토리

# archive 가 /archive/ 가 아닌 곳에 마운트된 경우:
# export ARCHIVE_DIR=/path/to/archive

python3 scripts/dump_mars_kpi_archive.py
```

- 실행 시간: **약 30분** (BQ chunks 3 tables × 3 fetchers × 12 monthly chunks = 108 queries)
- BQ scan: **약 432 GB** (cs/rs/users 합산)
- 비용: **약 $10** (BQ on-demand $6.25/TB) — 1회만

진행 상황은 stdout 으로:
```
2026-06-11 09:00:00 INFO === Mars rec KPI archive dump ===
2026-06-11 09:00:00 INFO   window: 2025-06-12 ~ 2026-06-10 (365 days)
2026-06-11 09:00:00 INFO [bq] client init: project=ai-develop-platform
2026-06-11 09:00:15 INFO [bq] 12345 rows, scanned 2.34 GB, job=abc...
2026-06-11 09:00:15 INFO [tvod_adultplus/cs] 2025-06-12~2025-07-12: 12345 rows, 31 files (15.0s)
...
```

### 빠른 검증 — 어제 1일치만

```bash
python3 scripts/dump_mars_kpi_archive.py --days 1
```

- 실행 시간: 약 1분
- 비용: $0.03
- **첫 실행 전 권장** — archive write 권한 + BQ 권한 확인

### 특정 옵션

```bash
# SVOD 만 1주 (비용 비싼 svod 만 빠르게 갱신)
python3 scripts/dump_mars_kpi_archive.py --tables svod --days 7

# 특정 윈도우
python3 scripts/dump_mars_kpi_archive.py --start 2026-01-01 --end 2026-06-10

# cs 만 (rs/users/meta 제외)
python3 scripts/dump_mars_kpi_archive.py --kinds cs --days 7

# 기존 파일 덮어쓰기 (default: skip)
python3 scripts/dump_mars_kpi_archive.py --overwrite
```

---

## 3. 출력 구조

```
{ARCHIVE_DIR}/mocha/mars_kpi/
├── tvod_adultplus/                # remy_mars_kpi_tod_adultplus_stats
│   ├── cs/{YYYYMMDD}.ftr          # date × content × counts (cs unnest)
│   ├── rs/{YYYYMMDD}.ftr          # date × rs.key × counts (rs unnest)
│   ├── users/{YYYYMMDD}.ftr       # date × unique_users / total_recommends
│   └── meta/{YYYYMMDD}.ftr        # 일별 elapsed median 등
├── svod/                          # remy_mars_kpi_stats (purchase_count 없음)
│   └── (cs / rs / users / meta)/
└── tvod_all/                      # remy_mars_kpi_tod_stats
    └── (cs / rs / users / meta)/
```

각 파일은 그날치 daily aggregation. mocha 가 윈도우 안의 일자 파일들을 concat 해서 사용.

---

## 4. 매일 cron 자동화 (선택)

매일 새벽 어제치만 incremental dump:

```bash
# crontab -e
0 4 * * * cd ~/mocha && python3 scripts/dump_mars_kpi_archive.py --days 1 >> ~/dump.log 2>&1
```

또는 Airflow / Argo Workflow 로:

```yaml
schedule: "0 4 * * *"  # 매일 04:00 KST
command: python3 scripts/dump_mars_kpi_archive.py --days 1
```

---

## 5. mocha site 가 archive 를 읽는 단계 (다음 PR)

dump 완료 후, mocha backend 가 archive 우선 → 없는 날짜만 BQ fallback 하도록 분기 추가가 필요합니다. (별도 PR 예정)

미리 dump 만 해두면 PR 머지 즉시 효과 발현 → 사이트 첫 진입 속도가 즉시 개선됩니다.

---

## 6. 문제 해결

### `ERROR: archive write 실패`

```
ERROR: archive write 실패 — [Errno 13] Permission denied: '...'
  target: /mnt/ml-archive/mocha/mars_kpi
```

→ 현재 archive 가 read-only 마운트. JupyterHub 환경에서 실행하거나 `ARCHIVE_DIR` 을 write 가능한 경로로 지정.

### `ERROR: google-cloud-bigquery 가 필요합니다`

```bash
pip install google-cloud-bigquery db-dtypes
```

### BQ 권한 없음 (403)

`gcloud auth application-default login` 또는 service account JSON 설정. ADP pod 에서는 IRSA 자동.

### 특정 chunk 실패 (한 달치)

로그에서 `[ERR]` 검색. 해당 윈도우만 재시도 — `--start`/`--end` 지정 후 `--overwrite`.

---

## 7. 비용 / 시간 견적

| 작업 | scan | cost | 시간 |
|---|---|---|---|
| **1년 1회 dump (3 tables × 3 fetchers)** | ~432 GB | **~$10** | ~30분 |
| 어제 1일치 (cron 매일) | ~1.2 GB | $0.03/일 | ~1분 |
| meta 1년치 (365 × small queries) | <1 GB | $1 | ~10분 |
| **dump 후 mocha site load** | 0 | **$0** | **~1-2s** |
