# MOCHA — 개선 사항 TODO

> 발표 후 / 다음 phase에서 진행할 항목들. 우선순위 + 시간 견적 포함.
> 작성: 2026-05-27 · 작성자: danielyun-watcha + Claude

---

## P0 — Production 배포 전 필수 (보안/안정성)

### 1. Basic auth default ON
- **현재**: `MOCHA_AUTH_USER` / `MOCHA_AUTH_PASS` env 설정 시에만 활성. cloudflared trycloudflare public URL이라 default off 시 **누구나 접근 가능**.
- **해결**: env 미설정 시 자동 token 생성 + log에 출력 (랜덤 8자). 또는 OAuth (claude.ai) 로그인 강제.
- **시간**: 1-2h

### 2. OAuth token 자동 refresh
- **현재**: `claudeAiOauth.expiresAt` 체크만, refresh logic 없음. 만료 시 graceful 503.
- **해결**: `refreshToken` 으로 5분 전 자동 갱신 (background task).
- **시간**: 2-3h

### 3. Anthropic 429 rate-limit retry
- **현재**: 429 응답 시 사용자에게 error 그대로 전달. Sonnet 한도 hit 시 mocha 답변 못 함.
- **해결**: Exponential backoff (1s, 2s, 4s) 최대 3회. 또는 자동 fallback (Sonnet → Haiku).
- **시간**: 1h

### 4. DB connection pool 조정
- **현재**: `min_size=1, max_size=10`. 동시 user 많아지면 stall.
- **해결**: `max_size=20`+ pool monitoring (acquire timeout log).
- **시간**: 30분

---

## P1 — 코드 품질 (큰 부채)

### 5. `main.py` 모듈 분리 (1700+ 라인)
- **현재**: routes / agent / charts / prompts / cleanup / auth / config 모두 단일 파일.
- **해결**:
  ```
  mocha/
    main.py            # FastAPI app + lifespan only
    routes/
      kpi.py           # /api/kpi/*
      chat.py          # /api/sessions/*/chat
      session.py       # /api/sessions
    agent/
      gateway.py       # _classify_local, gateway_classify
      fast_track.py    # OAuth direct + KPI inline
      slow_track.py    # claude_agent_sdk path
      prompts/         # *.md template files
    charts/
      base.py          # _chart_setup, _chart_save
      bar.py
      line.py
    util/
      cleanup.py
      auth.py
      cache.py
    config.py          # _Settings
  ```
- **시간**: 4-6h

### 6. Prompt template 외부 파일
- **현재**: `fast_system` 1300+ chars `f"""..."""` 하드코딩, 디버깅/diff 어려움.
- **해결**: `agent/prompts/fast_panda.md` 같은 Jinja2 template. `{{ kpi_json }}`, `{{ chart_path }}` placeholder.
- **시간**: 2h

### 7. Error handling 일관성
- **현재**: 일부 try/except graceful, 일부 raise, 일부 silent fail.
- **해결**: 공통 error decorator + structured error event (`{"type": "error", "code": "...", "message": "..."}`).
- **시간**: 2h

### 8. Type hints + mypy
- **현재**: 부분적. `dict[str, Any]` 위주.
- **해결**: 핵심 함수 타입 명시 + `mypy --strict` 통과.
- **시간**: 3h

---

## P2 — 정확도 / 인텔리전스

### 9. `_pick_chart` 검증 강화
- **현재**: smoke test가 "chart 있음" 만 체크. **올바른 chart** (intent → 매칭 chart name) 검증 X.
- **해결**: 각 demo query에 expected chart name 명시 + test assertion.
- **시간**: 1h

### 10. 인사이트 quality scoring
- **현재**: LLM 생성 그대로 신뢰. 같은 phrase 반복 / 무관 metric 사용 가능.
- **해결**: 인사이트 생성 후 LLM 1턴 추가로 self-critique (가벼운 모델). 또는 keyword 기반 무관 metric 감지.
- **시간**: 3h

### 11. Chart cache
- **현재**: 같은 query 반복 시 매번 PNG 재생성.
- **해결**: `(domain, period, chart_name)` 키로 chart cache. cleanup 시 함께 정리.
- **시간**: 2h

### 12. Token usage tracking
- **현재**: `usage` event는 dispatch만, 누적 통계 없음.
- **해결**: 일별 input/output token 누적 → DB 저장 → `/api/usage` endpoint. quota 추세 모니터링.
- **시간**: 2h

---

## P3 — 운영 / Production

### 13. 외부 PostgreSQL
- **현재**: `pgserver` embedded — single process, dev only.
- **해결**: 외부 PG (RDS / Cloud SQL) 연결. `pgserver` fallback 유지.
- **시간**: 1h (외부 인프라 별도)

### 14. uvicorn 다중 worker
- **현재**: 1 worker. 동시 처리 부족.
- **해결**: `--workers 4` + KPI cache를 Redis로 (현재 in-process dict — worker 간 공유 안 됨).
- **시간**: 4h (Redis 의존성)

### 15. CI + automated test
- **현재**: `_runtime/smoke_test.py` manual script.
- **해결**: GitHub Actions workflow — push 시 mocha startup + smoke test 자동.
- **시간**: 2h

### 16. Structured logging
- **현재**: `log.info(f"...")` plain text.
- **해결**: JSON log + correlation_id (session_id) per request. CloudWatch/Loki 호환.
- **시간**: 2h

### 17. Monitoring / alerting
- **현재**: 응답 시간 / 에러율 추적 없음.
- **해결**: Prometheus metrics endpoint (`/metrics`) — `mocha_request_duration_seconds`, `mocha_oauth_429_total` 등.
- **시간**: 3h

### 18. Daily prewarm cron
- **현재**: server startup 시만 prewarm. 24h 이상 동작 시 cache stale.
- **해결**: KST 새벽 4시 cron으로 전 도메인 prewarm 재실행 (subprocess).
- **시간**: 1h

---

## P4 — UX / 기능 확장

### 19. Mobile responsive
- **현재**: 데스크탑 전용. mobile에서 깨짐.
- **해결**: `@media (max-width: 768px)` rail collapsed + chat full width.
- **시간**: 3h

### 20. Multi-language
- **현재**: Korean 하드코딩.
- **해결**: `i18n.ts` (또는 vanilla) 영어/한국어 swap.
- **시간**: 4h

### 21. Chart accessibility
- **현재**: `<img alt="">` 빈 alt.
- **해결**: backend에서 chart 생성 시 alt 텍스트도 같이 ("MARS 장르별 인기 TOP 10 bar chart, Drama 1위 49.3%").
- **시간**: 1h

### 22. Session export
- **현재**: 답변 markdown 복사 버튼만. 전체 session export 없음.
- **해결**: `/api/sessions/{id}/export?format=md|pdf` — 모든 messages markdown / PDF로 다운.
- **시간**: 2h

### 23. EDA report 생성 (slow track)
- **현재**: slow track agent 거의 비활성. broad_eda도 fast track로 강제 처리 중.
- **해결**: 안정화된 slow track — claude_agent_sdk subprocess + Bash tool로 본격 EDA report 생성.
- **시간**: 6h+

---

## P5 — 기술 부채 / 가독성

### 24. DB schema versioning
- **현재**: `migrations/001_init.sql` 단일. up/down 없음.
- **해결**: `alembic` 또는 단순 version table + `migrations/00X_*.sql` 순차.
- **시간**: 2h

### 25. Frontend → TypeScript + 빌드 시스템
- **현재**: vanilla JS, 코드 산재 (`dashboard.js` 48KB, `app.js` 18KB).
- **해결**: Vite + TypeScript + 단일 entry. 또는 React/Vue (큰 작업).
- **시간**: 8h+

### 26. Test coverage
- **현재**: `smoke_test.py` 4개 query만.
- **해결**: pytest + KPI 계산식 단위 test (`_binary_rate`, `_per_user`, `_ucpu` 등) + endpoint integration test.
- **시간**: 4h

---

## 우선순위 정리

| Priority | Item | 합계 시간 |
|---|---|---:|
| **P0** | basic auth default / OAuth refresh / 429 retry / DB pool | **5h** |
| **P1** | 모듈 분리 / prompt template / error handling / type hints | **11h** |
| **P2** | chart verify / insight quality / chart cache / token tracking | **8h** |
| **P3** | 외부 PG / multi-worker / CI / logging / monitoring / cron | **13h** |
| **P4** | mobile / i18n / a11y / export / EDA report | **16h** |
| **P5** | DB version / FE refactor / test coverage | **14h** |
| **합계** | | **~67h** |

---

## 즉시 후속 권장 (발표 후 1순위)

1. **P0 #1 (basic auth)** — 1h, public tunnel 보안
2. **P0 #3 (429 retry)** — 1h, 안정성
3. **P1 #6 (prompt template 분리)** — 2h, 디버깅 용이
4. **P2 #9 (chart verify)** — 1h, regression 강화

합 5시간으로 안정성 / 유지보수성 큰 개선.

---

## 참고

- 현재 stack: FastAPI + uvicorn + pgserver + OAuth direct (Anthropic) + vanilla JS + Chart.js + marked.js
- Repo: https://github.com/danielyun-watcha/mocha
- 발표일 동작 보장: 4 demo query smoke test pass (`_runtime/smoke_test.py`)
