CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    sdk_session_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);

-- KPI AI 인사이트 캐시 (도메인 × 기간 × 콘텐츠필터)
CREATE TABLE IF NOT EXISTS kpi_insights (
    domain         TEXT NOT NULL,
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,
    content_types  TEXT NOT NULL DEFAULT '',
    bullets        JSONB NOT NULL,
    model          TEXT,
    elapsed_ms     INTEGER,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain, start_date, end_date, content_types)
);

-- KPI summary/series 결과 영구 저장 — 재시작해도 즉시 hit.
-- staleness: data 가 매일 1회 업데이트 → 같은 KST date 안에 만든 row 는 fresh.
CREATE TABLE IF NOT EXISTS kpi_summary_cache (
    domain         TEXT NOT NULL,
    start_date     DATE NOT NULL,
    end_date       DATE NOT NULL,
    content_types  TEXT NOT NULL DEFAULT '',
    summary_json   JSONB NOT NULL,
    series_json    JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (domain, start_date, end_date, content_types)
);
CREATE INDEX IF NOT EXISTS idx_kpi_summary_created ON kpi_summary_cache(created_at DESC);
