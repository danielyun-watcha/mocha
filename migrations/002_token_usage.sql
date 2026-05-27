-- Daily token usage rollup — OAuth subscription quota 추세 모니터링용.
-- aggregator (P3 #18 daily cron 등) 가 (date, model) 단위로 누적 update.
CREATE TABLE IF NOT EXISTS token_usage_daily (
    date            DATE NOT NULL,
    model           TEXT NOT NULL,
    input_tokens    BIGINT NOT NULL DEFAULT 0,
    output_tokens   BIGINT NOT NULL DEFAULT 0,
    cache_read      BIGINT NOT NULL DEFAULT 0,
    cache_creation  BIGINT NOT NULL DEFAULT 0,
    request_count   INTEGER NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (date, model)
);
CREATE INDEX IF NOT EXISTS idx_token_usage_date ON token_usage_daily(date DESC);
