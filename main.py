"""MOCHA — 자연어로 묻는 Watcha 데이터 분석 AI."""
from __future__ import annotations

# Logging: MOCHA_LOG_FORMAT=json 이면 structured JSON (CloudWatch/Loki 친화),
# 기본은 사람-친화 plain text. correlation_id 는 LoggerAdapter 로 부여.
import contextvars as _ctxvars
import json
import logging
import os
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from claude_agent_sdk import ClaudeAgentOptions, query
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import kpi as kpi_mod
import oauth_creds as _oauth_creds
import prompts as _prompts

_request_id_ctx: _ctxvars.ContextVar[str | None] = _ctxvars.ContextVar(
    "mocha_request_id", default=None
)
_session_id_ctx: _ctxvars.ContextVar[int | None] = _ctxvars.ContextVar(
    "mocha_session_id", default=None
)


class _JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "lvl": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        rid = _request_id_ctx.get()
        sid = _session_id_ctx.get()
        if rid:
            payload["request_id"] = rid
        if sid is not None:
            payload["session_id"] = sid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        sid = _session_id_ctx.get()
        rid = _request_id_ctx.get()
        ctx = ""
        if sid is not None or rid:
            bits = []
            if rid:
                bits.append(f"req={rid}")
            if sid is not None:
                bits.append(f"sess={sid}")
            ctx = " [" + " ".join(bits) + "]"
        base = f"{self.formatTime(record, '%Y-%m-%d %H:%M:%S,%f')[:-3]} {record.levelname} {record.name}{ctx} | {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_log_format = os.environ.get("MOCHA_LOG_FORMAT", "text").lower()
_log_handler = logging.StreamHandler(sys.stdout)
_log_handler.setFormatter(_JSONFormatter() if _log_format == "json" else _TextFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_log_handler], force=True)
log = logging.getLogger("mocha")

BASE_DIR = Path(__file__).parent
PLUGIN_DIR = BASE_DIR / "plugins" / "eda"
STATIC_DIR = BASE_DIR / "static"
MIGRATIONS_DIR = BASE_DIR / "migrations"

# ── Settings — all env-driven config in one place ───────────────────────────
class _Settings:
    """Single source of truth for env-driven config. Override via env vars."""
    PORT: int = int(os.environ.get("PORT", os.environ.get("DEV_PORT", 8080)))
    DATABASE_URL: str = os.environ["DATABASE_URL"]
    MODEL: str = os.environ.get("MOCHA_MODEL", "claude-sonnet-4-6")
    GATEWAY_MODEL: str = os.environ.get("MOCHA_GATEWAY_MODEL", "claude-haiku-4-5-20251001")
    FAST_LEAD_MODEL: str = os.environ.get("MOCHA_FAST_LEAD_MODEL", "claude-haiku-4-5-20251001")
    INSIGHT_MODEL: str = os.environ.get("MOCHA_INSIGHT_MODEL", "claude-haiku-4-5-20251001")
    MAX_BUDGET_USD: float = float(os.environ.get("MOCHA_MAX_BUDGET_USD", "3.0"))
    # 사실상 archive 범위 = cap. start_d 는 archive `min_d` 로 자동 clamp 되니까
    # 큰 값 둬도 안전. env 로 더 짧게 조이는 것도 가능.
    FAST_INLINE_MAX_DAYS: int = int(os.environ.get("MOCHA_FAST_INLINE_MAX_DAYS", "1000"))
    OAUTH_CRED_PATH: Path = Path(os.environ.get("CLAUDE_OAUTH_CRED", "/root/.claude/.credentials.json"))
    SESSION_RETENTION_DAYS: int = int(os.environ.get("MOCHA_SESSION_RETENTION_DAYS", "7"))
    CHART_RETENTION_HOURS: int = int(os.environ.get("MOCHA_CHART_RETENTION_HOURS", "24"))


cfg = _Settings()
# Backwards-compat aliases for existing code.
PORT = cfg.PORT
DATABASE_URL = cfg.DATABASE_URL
MODEL = cfg.MODEL

# OAuth: claude.ai team subscription 의 access token 으로 Anthropic API 직접 호출.
# API key (sk-ant-api03-...) 와 다른 인증 — subscription quota 만 소모, 추가 과금 X.
# Pure file readers extracted → oauth_creds.py (P1 #5 partial split).
_load_oauth_token = _oauth_creds.load_token
_oauth_expiry_seconds = _oauth_creds.expiry_seconds


async def _oauth_refresh_via_cli() -> bool:
    """Attempt to refresh token via `claude` CLI subprocess. Returns True on
    success. Anthropic 의 refresh endpoint 는 공개 spec 없음 → CLI 에 위임."""
    import asyncio
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "--print", "/login",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            proc.kill()
            return False
        return proc.returncode == 0
    except FileNotFoundError:
        return False
    except Exception:
        log.exception("[oauth-refresh] CLI invocation failed")
        return False


async def _oauth_refresh_loop() -> None:
    """Check OAuth expiry every 10min. If <15min left, attempt refresh.
    Refresh endpoint is not publicly documented → best-effort CLI delegation.
    Logs warning when expired so operator knows to run `claude /login`."""
    import asyncio
    while True:
        try:
            await asyncio.sleep(600)  # 10 minutes
            secs = _oauth_expiry_seconds()
            if secs is None:
                continue
            if secs < 0:
                log.warning("[oauth] token EXPIRED %.0fs ago — run `claude /login`", -secs)
            elif secs < 900:  # <15 min
                log.warning("[oauth] token expires in %.0fs — attempting CLI refresh", secs)
                ok = await _oauth_refresh_via_cli()
                log.info("[oauth] refresh result: %s", "ok" if ok else "failed (manual login needed)")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[oauth-refresh-loop] failed")


_OAUTH_BACKOFF_S = (1, 2, 4)  # exponential — max 3 attempts per model
_HAIKU_FALLBACK = "claude-haiku-4-5-20251001"

# 모듈 공유 httpx client — connection pool / TLS 세션 재사용.
# 이전엔 retry attempt 마다 새 AsyncClient 를 만들고 버려 매번 TLS 핸드셰이크 발생.
_HTTP_CLIENT: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _HTTP_CLIENT
    if _HTTP_CLIENT is None or _HTTP_CLIENT.is_closed:
        _HTTP_CLIENT = httpx.AsyncClient(timeout=60.0)
    return _HTTP_CLIENT


@asynccontextmanager
async def _shared_http_client() -> AsyncIterator[httpx.AsyncClient]:
    """공유 client 대여 — 블록 종료 시 닫지 않음(다음 요청에서 재사용)."""
    yield _get_http_client()


async def stream_oauth_completion(
    model: str, system: str, user_msg: str, max_tokens: int = 2048,
    history: list[dict] | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Stream Anthropic Messages via OAuth Bearer (team subscription quota).

    history: optional [{role:"user|assistant", content:"..."}] for multi-turn.
    Yields ('text', delta) chunks and a final ('done', cost_json).

    Retry policy:
      - 429 / 5xx: exponential backoff (1s,2s,4s), max 3 attempts on same model
      - Sonnet 429 exhausted → fallback to Haiku (notify user via 'text' event)
      - 4xx (non-429): immediate error, no retry
    """
    import asyncio as _asyncio
    token = _load_oauth_token()
    if not token:
        yield ("error", "OAuth token unavailable or expired — claude /login 필요")
        return
    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
        "accept": "text/event-stream",
    }
    messages = list(history or []) + [{"role": "user", "content": user_msg}]
    is_sonnet = "sonnet" in model.lower()
    models_to_try: list[str] = [model] + ([_HAIKU_FALLBACK] if is_sonnet and model != _HAIKU_FALLBACK else [])

    for try_idx, try_model in enumerate(models_to_try):
        if try_idx > 0:
            log.warning("[oauth] 429 exhausted on %s → fallback %s", model, try_model)
            if _PROM_AVAILABLE:
                try: OAUTH_FALLBACK.inc()
                except Exception: pass
            yield ("text", f"\n\n_⚠️ {model} rate-limit 한도 도달 → {try_model} 로 자동 fallback_\n\n")
        payload = {
            "model": try_model, "max_tokens": max_tokens, "stream": True,
            "system": system, "messages": messages,
        }

        last_status: int | None = None
        last_body: str = ""
        for attempt, backoff_s in enumerate(_OAUTH_BACKOFF_S):
            usage = {"input_tokens": 0, "output_tokens": 0}
            try:
                async with _shared_http_client() as client:
                    async with client.stream(
                        "POST", "https://api.anthropic.com/v1/messages",
                        headers=headers, json=payload,
                    ) as r:
                        if r.status_code != 200:
                            body_bytes = await r.aread()
                            last_status = r.status_code
                            last_body = body_bytes.decode(errors="replace")[:300]
                            retryable = r.status_code == 429 or 500 <= r.status_code < 600
                            if not retryable:
                                yield ("error", f"HTTP {r.status_code}: {last_body}")
                                return
                            # retryable: log + sleep then retry (unless last attempt)
                            log.warning(
                                "[oauth] %s try %d/%d HTTP %d, sleep %ds",
                                try_model, attempt + 1, len(_OAUTH_BACKOFF_S),
                                r.status_code, backoff_s,
                            )
                            if r.status_code == 429 and _PROM_AVAILABLE:
                                try: OAUTH_429.labels(model=try_model).inc()
                                except Exception: pass
                            if attempt < len(_OAUTH_BACKOFF_S) - 1:
                                await _asyncio.sleep(backoff_s)
                                continue
                            break  # exhausted, try fallback model if any
                        # 200 OK — stream
                        async for line in r.aiter_lines():
                            if not line or not line.startswith("data: "):
                                continue
                            try:
                                evt = json.loads(line[6:])
                            except json.JSONDecodeError:
                                continue
                            t = evt.get("type")
                            if t == "content_block_delta":
                                delta = evt.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    yield ("text", delta.get("text", ""))
                            elif t == "message_delta":
                                u = evt.get("usage") or {}
                                for k in ("input_tokens", "output_tokens",
                                          "cache_creation_input_tokens",
                                          "cache_read_input_tokens"):
                                    if k in u:
                                        usage[k] = u[k]
                            elif t == "message_start":
                                u = (evt.get("message") or {}).get("usage") or {}
                                for k, v in u.items():
                                    usage[k] = v
                yield ("done", json.dumps(usage))
                return
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_status = None
                last_body = str(e)
                log.warning("[oauth] %s try %d/%d network: %s", try_model,
                            attempt + 1, len(_OAUTH_BACKOFF_S), e)
                if attempt < len(_OAUTH_BACKOFF_S) - 1:
                    await _asyncio.sleep(backoff_s)
                    continue
                break
            except Exception as e:
                log.exception("OAuth streaming failed")
                yield ("error", f"streaming error: {e}")
                return
        # exhausted this model — loop tries next (fallback) if any

    yield ("error",
           f"rate-limited / unavailable after retries: HTTP {last_status} {last_body}")

# 세션당 USD 캡 — 풀 EDA 1회 실측 ~$1.6, 2배 헤드룸으로 $3.
# 폭주(무한 루프 등) 가드. 초과 시 ResultMessage(subtype="error_max_budget_usd").
MAX_BUDGET_USD = cfg.MAX_BUDGET_USD  # single source: _Settings
# NOTE: TaskBudget(token pacing hint)은 beta header(task-budgets-2026-03-13) 가 필요해서
# sonnet-4-6 같은 일반 모델에선 API 400. Opus 일부 버전만 지원. 안정성 위해 비활성.
# max_budget_usd 만으로 폭주 가드 충분.

DOMAIN_SPECS = {
    "pedia": """pedia/GALAXY (rate/wish-centric)
logs: /archive/rec_galaxy/behavior_logs/YYYYMMDD_YYYYMMDD.ftr
  cols: user_id i64 · content_type i8 (1=Movie 2=TvSeason 4=Book 8=Webtoon) · content cat · action_type i (1=RATE 2=WISH 6=SEARCH 7=CLICK) · value i64 · timestamp unix-sec
ratings: /archive/rating_prediction/default/ratings.ftr (1-10, updated_at UTC)
meta: /archive/foundation_tmp/items/{movie,tv_season,book,webtoon}/meta.parquet (main_genre_name)
people: /archive/graph_modeling/builtin/{content_credit_edges,person_id_to_name}.pkl
NO: price/revenue (not in archive).""",

    "watcha_main": """watcha_main/MARS (watch-centric)
logs: /archive/user_bert/behavior_logs2/train/YYYYMMDD_YYYYMMDD.ftr (monthly cumulative)
  cols: user_id i64 · timestamp i64 · action_type cat (CLICK:MARS|PLAY:MARS|WISH:MARS|SEARCH:MARS|RATE:MARS) · content cat · rating i64
  WARN: galaxy events mixed in. Filter action_type.str.endswith(":MARS") then split(":").
ratings: /archive/rating_prediction/default/ratings.ftr (shared with galaxy)
meta: foundation_tmp/items/{movie,tv_season,webtoon}/meta.parquet
people: graph_modeling/builtin/ (same as galaxy)
content_type: 1=Movie 2=TvSeason 5=TvEpisode 8=Webtoon 10=AdultMovie 11=AdultWebtoon
NO: price/revenue (not in archive — mysql/bq needed).""",

    "adult": """adult/ADULT (purchase-centric)
logs: /archive/rec_adult/behavior_logs/YYYYMMDD_YYYYMMDD.ftr
  cols: user_id I64 · content cat · timestamp I64 · action_type cat (click|preview|play|wish|rental|possession) · response_id
price: /archive/rec_adult/builtin/CONTENT_TO_PRICE.pkl (dict {rental:{cid:price},possession:{cid:price}})
  cid = int from content "10:XXXX". eg 1650/2750/5500원
meta (ID only, no name in archive): CID_TO_ACTORID/DIRECTORID/AGEID/BODYTYPEID/NATIONID/SITUATIONID (.pkl sparse mat)
content_type: 10=AdultMovie
NO: actor/director names (mysql lookup needed).""",

    "unknown": "unknown domain — ask user to specify.",
}

# KPI endpoint — agent calls curl instead of pandas scouting
KPI_ENDPOINT_GUIDE = """
## KPI ENDPOINT (use FIRST for KPI/TOP/dist questions — skip pandas)

curl -s "http://localhost:8090/api/kpi/{domain}/summary?start=YYYY-MM-DD&end=YYYY-MM-DD"
domains: galaxy|mars|adult. Response in <1s.

Response keys (common, some domain-specific):
- kpis [{label,value,fmt}] — DAU, 1인당 활동/평가/재생/구매, CVR, 평가율, 시청율, 구매율, Strong 신호 비율, Cold Start, Long-tail TOP 5%, 재방문율, 희소성, 평균 평점, 재시청률, etc.
- timeseries [{date,events,users}]
- actions [{label,count}]
- top_contents | top_genres | top_revenue_contents | top_actors | top_directors | top_rated_contents
- rating_distribution (galaxy/mars), hourly_activity (KST), pareto_curve
- revenue (adult only): {total_revenue, paying_users, revenue_per_paying_user, daily_revenue, top_payers[:10] {user_id,revenue,purchases}}
- content_type_breakdown (galaxy/mars), supports, files_read, elapsed_ms

Patterns:
- GALAXY 평균 평점 → galaxy summary → kpis.평균평점
- ADULT 매출/큰손 → adult summary → revenue.total_revenue or revenue.top_payers[0]
- MARS TOP 감독 → mars summary → top_directors[:5]
- GALAXY 시간대 → galaxy summary → hourly_activity
- 평점높은 영화 TOP → mars/galaxy summary → top_rated_contents

Filter (galaxy only): &content_types=movie,tv
Single-metric series (modal): /api/kpi/{domain}/series?start=...&end=...&label=DAU

Use raw archive ONLY when endpoint cannot cover (custom segmentation, new metric).
"""


SYSTEM_PROMPT_TEMPLATE = """\
You are MOCHA — Watcha internal data analyst. Answer in **Korean**.

## RULE 1: ONE Bash call (single Python block). NO scouting/head/dtype/retry.
Schema is in DOMAIN below — use as-is, no guessing.
Bundle in ONE block: import (pandas, matplotlib, NanumGothic) + load + analyze + save chart + print.
NARROW or BROAD — same rule. If first try might fail, write more carefully. NO second Bash.
(Exception) Follow-up question from user → next Bash OK. Same question → 1 Bash only.

## DOMAIN (Gateway-assigned — access only this archive scope)

{domain_block}

IRON RULE: never read outside the archive paths above. Ambiguous → ask user once.

{kpi_endpoint_guide}

## Sub-skills (standalone, only when really needed)
Skill(eda-figures) themed charts · eda-overview basic stats · eda-casestudy TOP cases · eda-report Markdown · eda-intake brief · notion-publish.
Simple stats/viz → pandas+matplotlib directly is faster. Sub-skill only when "themed consistency" or "standard report format" is required.

## Answer templates (plugins/eda/templates/)
Pick 1 by question type → Read → fill placeholders:
- 01_light_memo.md — TOP N / dist / simple stat (30-50 lines)
- 02_full_eda.md — EDA / overview (150-300 lines)
- 03_ab_test.md — A/B post (200-400 lines)
- 04_analysis_report.md — mid analysis note (100-200 lines)

## Answer rules
- Korean output. PANDA format: question summary → table/chart → aggregation basis → 💡 **1-line insight** (+1 optional).
- Markdown length: NARROW 500-700 chars / BROAD 1500+. No tangents, core only.
- Save viz to /tmp/eda/*.png, embed `![](/eda-files/X.png)`. NEVER just give the path.
- 1 file per chart. Caveats only as final line.

## Chart design (Toss PANDA / NYT / Datawrapper style — apply on every matplotlib call)

```python
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import os
# Korean font (container first, workspace fallback)
for p in ('/usr/share/fonts/truetype/nanum/NanumGothic.ttf',
          '/home/daniel/.fonts/NanumGothic.ttf'):
    if os.path.exists(p):
        fm.fontManager.addfont(p); break
plt.rcParams.update({
    'font.family': 'NanumGothic',
    'axes.unicode_minus': False,
    'figure.facecolor': 'white', 'axes.facecolor': 'white', 'savefig.facecolor': 'white',
    'savefig.dpi': 200, 'savefig.bbox': 'tight',
    'axes.titlesize': 16, 'axes.titleweight': 'bold', 'axes.titlelocation': 'left',
    'axes.labelsize': 12, 'axes.labelcolor': '#555',
    'xtick.labelsize': 11, 'ytick.labelsize': 11,
    'xtick.color': '#555', 'ytick.color': '#555',
    'axes.edgecolor': '#999', 'axes.linewidth': 0.8,
})
```

Bar (vert/horiz):
1. White bg. No dark/neon.
2. Palette: highlight 1 color, rest gray.
   - highlight (TOP1-3): #E89B9B (pastel red) or #d97757 (warm)
   - non-highlight: #D8D5CC (light beige gray)
   - critical: #c93636 (rare)
3. edgecolor='none', linewidth=0 (no bar separation).
4. ax.grid(False) — no horizontal gridlines. Values labeled directly on bars.
5. Remove top/right spines, left/bottom light gray (auto via rcParams).
6. Data labels above (vert) / right (horiz) of every bar:
   ```python
   for bar, v in zip(bars, vals):
       ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+max(vals)*0.015,
               f'{v:,}', ha='center', fontsize=10, color='#333')
   ```
7. figsize: vert (10,5.5) / horiz (10,7).
8. Title: left-aligned, color #1a1a1a, **single line** (loc='left', pad=20). Meta in same title line with ` · ` separator:
   - good: "TOP 10 인기 영화 · ML-1M · min-20 필터"
   - good: "장르별 영화 수 분포 · 18개 장르 · 3,883편"
   - FORBIDDEN: plt.suptitle / fig.text / ax.text(transform=ax.transAxes) — overlaps with title.

Item count rule (table & figure):
- >20 items → TOP 10 only.
- ≤20 items (genre/gender/weekday) → show ALL, gray solid, only TOP 1-3 highlight color.
- TOP-N (ranking): user N first, else 10.
- bars>12 → horizontal preferred.
- horizontal label long → figsize (11, ...) or truncate with `…` over 30 chars.

Output: plt.tight_layout(); plt.savefig(path); plt.close(). PNG 200 DPI.
Charts violating these rules MUST be regenerated.
"""


def build_system_prompt(domain: str = "unknown") -> str:
    """Gateway 가 정한 domain 의 spec 만 포함시켜 SYSTEM_PROMPT 생성.

    전체 도메인 표 (~5개 행) → 1개 행만 주입 → input token ~40% 절감.
    Phase 2 부활 시 Domain Expert 의 system_prompt 와 일관된 구조.
    """
    spec = DOMAIN_SPECS.get(domain, DOMAIN_SPECS["unknown"])
    # NOTE: .replace 사용 — str.format 은 시각화 룰의 `{...}` (plt.rcParams 등) 를
    # placeholder 로 잘못 해석해 KeyError. domain spec 은 단순 치환이 안전.
    return (
        SYSTEM_PROMPT_TEMPLATE
        .replace("{domain_block}", spec)
        .replace("{kpi_endpoint_guide}", KPI_ENDPOINT_GUIDE)
    )

db_pool: asyncpg.Pool | None = None

# Detached background tasks (e.g. long-period prewarm) — ref 보관용.
# 보관 안 하면 GC 가 실행 중 task 를 수거할 수 있고 shutdown 시 정리도 누락됨.
_BG_TASKS: set = set()


async def _hydrate_kpi_cache_from_db() -> None:
    """서버 startup 시 호출: DB 의 KPI summary/series 캐시를 in-memory 로 로드.

    Staleness: 같은 KST date 안에 만들어진 row 만 fresh (사용자 명시 — 데이터는
    하루 1회 갱신).  Stale row 는 hydrate skip → 다음 prewarm 이 재계산."""
    from datetime import datetime, timedelta, timezone
    kst = timezone(timedelta(hours=9))
    today_kst_midnight_utc = (
        datetime.combine(datetime.now(kst).date(), datetime.min.time(), tzinfo=kst)
        .astimezone(timezone.utc)
    )
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT domain, start_date, end_date, content_types, "
            "       summary_json, series_json, created_at "
            "FROM kpi_summary_cache WHERE created_at >= $1",
            # Hydrate from last 3 days (was today-only). Stale-ish 1 query
            # is much better UX than 10s cold path on first dashboard load.
            # Daily prewarm will overwrite with fresh numbers.
            today_kst_midnight_utc - timedelta(days=2),
        )
    pairs = []
    for r in rows:
        cts = r["content_types"] or ""
        s_iso = r["start_date"].isoformat()
        e_iso = r["end_date"].isoformat()
        s = r["summary_json"]
        if isinstance(s, str): s = json.loads(s)
        pairs.append(("summary", r["domain"], s_iso, e_iso, cts, s))
        if r["series_json"]:
            sj = r["series_json"]
            if isinstance(sj, str): sj = json.loads(sj)
            pairs.append(("series", r["domain"], s_iso, e_iso, cts, sj))
    n = kpi_mod.hydrate_cache(pairs)
    log.info(f"[hydrate] loaded {n} cache rows from DB (last 3 days, KST)")
    return n


async def _persist_kpi_cache(
    domain: str, start_d: Any, end_d: Any, cts_str: str,
    summary: dict, series: dict,
) -> None:
    """Persist KPI cache to PG. Tolerate timeouts — in-memory cache still wins,
    DB persist is only for restart hydration. Log + return on failure."""
    try:
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO kpi_summary_cache(domain, start_date, end_date, content_types, "
                "summary_json, series_json) VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb) "
                "ON CONFLICT (domain, start_date, end_date, content_types) DO UPDATE "
                "SET summary_json=EXCLUDED.summary_json, "
                "    series_json=EXCLUDED.series_json, created_at=NOW()",
                domain, start_d, end_d, cts_str,
                json.dumps(summary), json.dumps(series) if series else None,
            )
    except Exception as e:
        log.warning(f"[persist-cache] {domain} {start_d}~{end_d} skipped: {type(e).__name__} ({e})")


# Lazy filter prewarm — domain×start×end 단위로 한 번만 실행
_LAZY_PREWARMED: set = set()
_LAZY_PREWARM_SEM = None  # initialized in lifespan


async def _lazy_prewarm_filters(domain: str, start_d, end_d) -> None:
    """도메인 단일 content_type / action_type 필터 조합을 background 로 캐시.

    사용자가 default 진입 후 1-2분 안에 단일 필터 클릭 시 즉시 응답."""
    import asyncio
    key = (domain, start_d, end_d)
    # asyncio 단일 스레드 + check~add 사이 await 없음 → race 없음.
    # 장기 가동 시 rolling date 로 무한 증가 방지용 cap (초과 시 reset).
    if key in _LAZY_PREWARMED:
        return
    if len(_LAZY_PREWARMED) >= 256:
        _LAZY_PREWARMED.clear()
    _LAZY_PREWARMED.add(key)
    # serialize across all lazy prewarms (server overload 방지)
    global _LAZY_PREWARM_SEM
    if _LAZY_PREWARM_SEM is None:
        _LAZY_PREWARM_SEM = asyncio.Semaphore(1)
    async with _LAZY_PREWARM_SEM:
        t0 = time.time()
        ct_opts = (kpi_mod.GALAXY_CONTENT_TYPES if domain == "galaxy"
                   else kpi_mod.MARS_CONTENT_TYPES if domain == "mars" else [])
        at_opts = kpi_mod.ACTION_TYPES.get(domain, [])

        # 단일 content_type (summary 만 — series 는 사용자 lazy fetch 가 처리)
        for ct in ct_opts:
            try:
                await asyncio.to_thread(
                    kpi_mod.summary, domain, start_d, end_d, [ct["key"]], None
                )
            except Exception:
                log.exception(f"[lazy-prewarm] {domain} ct={ct['key']}")

        # 단일 action_type
        for at in at_opts:
            try:
                await asyncio.to_thread(
                    kpi_mod.summary, domain, start_d, end_d, None, [at]
                )
            except Exception:
                log.exception(f"[lazy-prewarm] {domain} at={at}")
        log.info(
            f"[lazy-prewarm] {domain} {start_d}~{end_d}: "
            f"{len(ct_opts)} cts + {len(at_opts)} ats in {time.time()-t0:.1f}s"
        )


async def _long_prewarm_subprocess() -> None:
    """30-day fast-inline KPI prewarm — each domain in its own subprocess.

    main asyncio loop stays responsive (no GIL). After child exits, read
    the persisted row from DB and hot-load into in-memory cache so the
    very next user query hits instantly.
    """
    import asyncio
    from datetime import date as _date
    from datetime import timedelta
    await asyncio.sleep(20)  # give initial user traffic priority
    log.info("[long-prewarm-sp] starting (subprocess per domain)…")
    for domain in ("galaxy", "mars", "adult"):
        try:
            rng = kpi_mod.available_range(domain)
            if not rng["max"]:
                continue
            end_d = _date.fromisoformat(rng["max"])
            min_d = _date.fromisoformat(rng["min"])
            start_d = max(end_d - timedelta(days=29), min_d)
            sum_key = ("summary", domain, start_d.isoformat(), end_d.isoformat(), tuple())
            if kpi_mod._cache_get(sum_key):
                log.info(f"[long-prewarm-sp] {domain} 30d: in-memory hit, skip")
                continue
            # Already in DB? hydrate without spawning.
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT summary_json, series_json FROM kpi_summary_cache "
                    "WHERE domain=$1 AND start_date=$2 AND end_date=$3 AND content_types=''",
                    domain, start_d, end_d,
                )
            if row:
                _hydrate_cache_row(domain, start_d, end_d, row)
                log.info(f"[long-prewarm-sp] {domain} 30d: DB hit, hydrated")
                continue

            t0 = time.time()
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(BASE_DIR / "_runtime" / "prewarm_one.py"),
                domain, start_d.isoformat(), end_d.isoformat(),
                env={**os.environ, "DATABASE_URL": DATABASE_URL},
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            dur = time.time() - t0
            if proc.returncode != 0:
                log.warning(f"[long-prewarm-sp] {domain} 30d failed ({dur:.1f}s): "
                            f"{stderr.decode()[:200]}")
                continue
            # Subprocess wrote row → hydrate into our process.
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT summary_json, series_json FROM kpi_summary_cache "
                    "WHERE domain=$1 AND start_date=$2 AND end_date=$3 AND content_types=''",
                    domain, start_d, end_d,
                )
            if row:
                _hydrate_cache_row(domain, start_d, end_d, row)
                log.info(f"[long-prewarm-sp] {domain} 30d built+hydrated in {dur:.1f}s")
            else:
                log.warning(f"[long-prewarm-sp] {domain} subprocess succeeded but no DB row")
        except Exception:
            log.exception(f"[long-prewarm-sp] {domain} failed")
    log.info("[long-prewarm-sp] done")


def _hydrate_cache_row(domain: str, start_d, end_d, row) -> None:
    """Push a DB cache row back into kpi_mod's in-memory cache."""
    sum_key = ("summary", domain, start_d.isoformat(), end_d.isoformat(), tuple())
    ser_key = ("series", domain, start_d.isoformat(), end_d.isoformat(), tuple())
    try:
        summary = json.loads(row["summary_json"]) if isinstance(row["summary_json"], str) else row["summary_json"]
        if summary:
            kpi_mod._cache_put(sum_key, summary)
        if row["series_json"]:
            series = json.loads(row["series_json"]) if isinstance(row["series_json"], str) else row["series_json"]
            kpi_mod._cache_put(ser_key, series)
    except Exception:
        log.exception(f"hydrate failed for {domain} {start_d}~{end_d}")


async def prewarm_dashboards() -> None:
    """Startup background task — DB hit 면 skip, miss 면 계산 + DB upsert.

    데이터가 하루 1회 갱신되니까 같은 KST date 안에 이미 계산된 row 가 있으면
    재계산 안 함.  서버 재시작 후에도 즉시 응답."""
    import asyncio
    from datetime import date as _date
    from datetime import timedelta
    await asyncio.sleep(2)
    log.info("[prewarm] starting…")
    # 무거운 메타 lazy load — rating_prediction 일자별 사전 집계 (244M → 작은 집계)
    try:
        t_rp = time.time()
        await asyncio.to_thread(kpi_mod._load_rp_daily)
        log.info(f"[prewarm] rating_prediction daily agg: {time.time()-t_rp:.1f}s")
    except Exception:
        log.exception("[prewarm] rp_daily failed")
    for domain in ("galaxy", "mars", "adult"):
        try:
            rng = kpi_mod.available_range(domain)
            if not rng["max"]:
                continue
            end_d = _date.fromisoformat(rng["max"])
            start_d = end_d - timedelta(days=6)

            # in-memory hit? (hydrate already loaded valid DB rows)
            sum_key = ("summary", domain, start_d.isoformat(), end_d.isoformat(), tuple())
            ser_key = ("series", domain, start_d.isoformat(), end_d.isoformat(), tuple())
            sum_hit = kpi_mod._cache_get(sum_key)
            ser_hit = kpi_mod._cache_get(ser_key)
            if sum_hit and ser_hit:
                log.info(f"[prewarm] {domain}: skip (DB cache hit)")
                continue

            t0 = time.time()
            summary = kpi_mod.summary(domain, start_d, end_d)
            series = kpi_mod.series_response(domain, start_d, end_d)
            await _persist_kpi_cache(domain, start_d, end_d, "", summary, series)
            kpi_dur = time.time() - t0

            # insight — DB check
            async with db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT 1 FROM kpi_insights WHERE domain=$1 AND start_date=$2 "
                    "AND end_date=$3 AND content_types=''",
                    domain, start_d, end_d,
                )
            if not row:
                t1 = time.time()
                ins = await _generate_insights(domain, start_d, end_d, None)
                ins_dur = time.time() - t1
                if ins.get("bullets"):
                    async with db_pool.acquire() as conn:
                        await conn.execute(
                            "INSERT INTO kpi_insights(domain, start_date, end_date, "
                            "content_types, bullets, model, elapsed_ms) "
                            "VALUES($1,$2,$3,'',$4::jsonb,$5,$6) "
                            "ON CONFLICT (domain, start_date, end_date, content_types) DO NOTHING",
                            domain, start_d, end_d,
                            json.dumps(ins["bullets"]), INSIGHT_MODEL, int(ins_dur * 1000),
                        )
                log.info(f"[prewarm] {domain}: kpi {kpi_dur:.1f}s, insight {ins_dur:.1f}s ✓")
            else:
                log.info(f"[prewarm] {domain}: kpi {kpi_dur:.1f}s, insight cached ✓")
        except Exception:
            log.exception(f"[prewarm] {domain} failed")
    log.info("[prewarm] done")

    # Long-period (30d) prewarm — runs as **detached subprocess** so the
    # main asyncio loop / web server stays responsive (pandas GIL isolated
    # in the child process). Result lands in kpi_summary_cache (DB), main
    # hydrates it into in-memory on completion.
    _t = asyncio.create_task(_long_prewarm_subprocess())
    _BG_TASKS.add(_t)
    _t.add_done_callback(_BG_TASKS.discard)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    import asyncio
    log.info("Connecting to PostgreSQL")
    # KPI summary JSON 이 수 MB(특히 galaxy) — asyncpg 의 prepared statement cache 가
    # 큰 JSONB 적재 시 prepare 단계에서 멈추는 케이스가 있어 cache=0 + 넉넉한 timeout.
    db_pool = await asyncpg.create_pool(
        DATABASE_URL, min_size=2, max_size=20, timeout=5.0,
        command_timeout=120.0,
        statement_cache_size=0,
    )
    # Apply migrations 순차적 — schema_migrations 테이블이 version 추적.
    # 새 .sql 파일을 migrations/ 에 NNN_name.sql (3자리 번호) 형식으로 추가만 하면 됨.
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        applied = 0
        for sql_file in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
            version = sql_file.stem  # e.g. "001_init"
            row = await conn.fetchrow(
                "SELECT 1 FROM schema_migrations WHERE version=$1", version
            )
            if row:
                continue
            log.info("[migrate] applying %s", version)
            await conn.execute(sql_file.read_text())
            await conn.execute(
                "INSERT INTO schema_migrations(version) VALUES($1)", version
            )
            applied += 1
    log.info(
        "Migrations: %d new applied. Listening on :%d (model=%s, max_budget=$%.2f)",
        applied, PORT, MODEL, MAX_BUDGET_USD,
    )

    # Hydrate in-memory KPI cache from DB (skip if today's row already exists)
    try:
        await _hydrate_kpi_cache_from_db()
    except Exception:
        log.exception("[hydrate] failed (continuing anyway)")

    # Pre-warm matplotlib (Korean font registration is ~3-5s cold) so first
    # chart in a chat answer is fast.
    try:
        _chart_setup()
        log.info("[startup] matplotlib pre-warmed")
    except Exception:
        log.exception("[startup] matplotlib pre-warm failed (continuing)")

    # Background prewarm — DB cache hit if today's row present, else compute
    prewarm_task = asyncio.create_task(prewarm_dashboards())

    # Periodic cleanup: old session messages + stale chart files
    cleanup_task = asyncio.create_task(_periodic_cleanup())

    # Daily prewarm cron — KST 04:00 마다 모든 도메인 prewarm 재실행
    # (24h+ 동작 시 cache stale 방지)
    daily_prewarm_task = asyncio.create_task(_daily_prewarm_loop())

    # OAuth token refresh monitor — 만료 임박 시 자동 갱신 (CLI 위임)
    oauth_refresh_task = asyncio.create_task(_oauth_refresh_loop())

    yield

    log.info("Shutting down")
    prewarm_task.cancel()
    cleanup_task.cancel()
    daily_prewarm_task.cancel()
    oauth_refresh_task.cancel()
    for _t in list(_BG_TASKS):
        _t.cancel()
    if _HTTP_CLIENT is not None and not _HTTP_CLIENT.is_closed:
        await _HTTP_CLIENT.aclose()
    if db_pool is not None:
        await db_pool.close()


async def _daily_prewarm_loop() -> None:
    """Sleep until next KST 04:00 then run prewarm_dashboards(). Repeats forever."""
    import asyncio
    from datetime import datetime, timedelta, timezone
    KST = timezone(timedelta(hours=9))
    while True:
        try:
            now = datetime.now(KST)
            next_run = now.replace(hour=4, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            delay = (next_run - now).total_seconds()
            log.info("[daily-prewarm] sleeping %.0fs until %s KST", delay, next_run.isoformat())
            await asyncio.sleep(delay)
            log.info("[daily-prewarm] firing scheduled prewarm")
            await prewarm_dashboards()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[daily-prewarm] failed (sleeping 1h then retry)")
            await asyncio.sleep(3600)


async def _periodic_cleanup() -> None:
    """Hourly cleanup: chat sessions >7d, /tmp/eda/sess_* >24h."""
    import asyncio
    import shutil
    from datetime import datetime, timedelta, timezone
    while True:
        try:
            await asyncio.sleep(60)  # initial delay
            # 1) DB: sessions >7d old → delete (cascade messages)
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            async with db_pool.acquire() as conn:
                deleted = await conn.fetchval(
                    "WITH d AS (DELETE FROM sessions WHERE updated_at < $1 RETURNING id) "
                    "SELECT count(*) FROM d", cutoff,
                )
            if deleted:
                log.info(f"[cleanup] deleted {deleted} old sessions (>7d)")
            # 2) /tmp/eda/sess_* dirs >24h
            cutoff_ts = time.time() - 86400
            removed = 0
            for d in EDA_DIR.glob("sess_*"):
                try:
                    if d.is_dir() and d.stat().st_mtime < cutoff_ts:
                        shutil.rmtree(d)
                        removed += 1
                except Exception:
                    pass
            if removed:
                log.info(f"[cleanup] removed {removed} old sess_* dirs (>24h)")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[cleanup] iteration failed")
        await asyncio.sleep(3600)  # then every hour


app = FastAPI(lifespan=lifespan, title="MOCHA")


@app.middleware("http")
async def correlation_and_cache(request, call_next):
    """request_id ContextVar 부여 + Prometheus duration + 정적 자산 no-cache."""
    import uuid as _uuid
    rid = request.headers.get("x-request-id") or _uuid.uuid4().hex[:12]
    token = _request_id_ctx.set(rid)
    t0 = time.time()
    try:
        response = await call_next(request)
    finally:
        _request_id_ctx.reset(token)
    response.headers["x-request-id"] = rid
    # 보안 헤더 — XSS backstop (DOMPurify 가 뚫려도 외부 script 차단), clickjacking 방지.
    # script 는 전부 same-origin self-host. style/font 만 폰트 CDN(jsdelivr) 허용.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "font-src 'self' https://cdn.jsdelivr.net data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    # Prometheus: path template 으로 cardinality 제한 (raw path 쓰면 폭증)
    if _PROM_AVAILABLE and path != "/metrics":
        route = getattr(request.scope.get("route"), "path", path)
        try:
            REQ_DURATION.labels(
                method=request.method, path_template=route,
                status=str(response.status_code),
            ).observe(time.time() - t0)
        except Exception:
            pass
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Prometheus metrics ─────────────────────────────────────────────
try:
    from prometheus_client import CONTENT_TYPE_LATEST as _PROM_CT
    from prometheus_client import Counter as _PromCounter
    from prometheus_client import Histogram as _PromHistogram
    from prometheus_client import generate_latest as _prom_dump
    _PROM_AVAILABLE = True

    REQ_DURATION = _PromHistogram(
        "mocha_request_duration_seconds",
        "HTTP request duration",
        ["method", "path_template", "status"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25, 60),
    )
    OAUTH_429 = _PromCounter(
        "mocha_oauth_429_total", "OAuth 429 responses", ["model"]
    )
    OAUTH_FALLBACK = _PromCounter(
        "mocha_oauth_fallback_total",
        "OAuth model fallback events (Sonnet → Haiku)",
    )
    CHART_CACHE_HIT = _PromCounter(
        "mocha_chart_cache_total", "Chart PNG cache outcomes", ["outcome"]
    )
except ImportError:
    _PROM_AVAILABLE = False
    log.warning("[metrics] prometheus_client not installed — /metrics disabled")


@app.get("/metrics")
async def metrics() -> Response:
    """Prometheus text-format metrics."""
    if not _PROM_AVAILABLE:
        return Response("prometheus_client not installed", status_code=503)
    return Response(_prom_dump(), media_type=_PROM_CT)


async def _record_token_usage(model: str, usage: dict) -> None:
    """Upsert daily token totals — (date, model) 기준 누적."""
    if not db_pool:
        return
    from datetime import date as _date
    today = _date.today()
    input_t = int(usage.get("input_tokens", 0))
    output_t = int(usage.get("output_tokens", 0))
    cache_read = int(usage.get("cache_read_input_tokens", 0))
    cache_creation = int(usage.get("cache_creation_input_tokens", 0))
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO token_usage_daily(date, model, input_tokens, output_tokens,
                                          cache_read, cache_creation, request_count)
            VALUES($1, $2, $3, $4, $5, $6, 1)
            ON CONFLICT (date, model) DO UPDATE SET
                input_tokens   = token_usage_daily.input_tokens + EXCLUDED.input_tokens,
                output_tokens  = token_usage_daily.output_tokens + EXCLUDED.output_tokens,
                cache_read     = token_usage_daily.cache_read + EXCLUDED.cache_read,
                cache_creation = token_usage_daily.cache_creation + EXCLUDED.cache_creation,
                request_count  = token_usage_daily.request_count + 1,
                updated_at     = NOW()
            """,
            today, model, input_t, output_t, cache_read, cache_creation,
        )


@app.get("/api/usage")
async def usage_summary(days: int = 7) -> dict:
    """최근 N일 token 사용량 합계 (date 단위 + model 단위)."""
    if not db_pool:
        return {"days": days, "rows": []}
    days = max(1, min(int(days), 90))
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT date, model, input_tokens, output_tokens,
                   cache_read, cache_creation, request_count
            FROM token_usage_daily
            WHERE date >= CURRENT_DATE - $1::int
            ORDER BY date DESC, model
            """,
            days - 1,
        )
    return {
        "days": days,
        "rows": [
            {
                "date": str(r["date"]),
                "model": r["model"],
                "input": int(r["input_tokens"]),
                "output": int(r["output_tokens"]),
                "cache_read": int(r["cache_read"]),
                "cache_creation": int(r["cache_creation"]),
                "requests": int(r["request_count"]),
            }
            for r in rows
        ],
    }


@app.get("/debug")
async def debug_page() -> StreamingResponse:
    """Browser-side debug page — no JS, no CSS, just raw status of mocha.

    DevTools 없이도 사이트가 정상인지 확인 가능. 모든 KPI / insights
    endpoint 직접 호출 + 결과 표시."""
    from datetime import timedelta
    rows = ["<h1>🔍 MOCHA Debug</h1><pre>"]
    rows.append(f"server time: {int(time.time())}s")
    rows.append(f"db_pool: {'OK' if db_pool else 'NONE'}")
    rows.append("")
    rows.append("=== 도메인별 KPI / Insight cache 상태 ===")
    for domain in ("galaxy", "mars", "adult"):
        try:
            _, end_d = kpi_mod.available_range_dates(domain)
            if end_d is None:
                rows.append(f"  {domain:8s} no archive data")
                continue
            start_d = end_d - timedelta(days=6)
            sum_key = ("summary", domain, start_d.isoformat(), end_d.isoformat(), tuple(), tuple())
            in_mem = "HIT" if kpi_mod._cache_get(sum_key) else "MISS"
            rows.append(f"  {domain:8s} default {start_d}~{end_d}  in-memory: {in_mem}")
        except Exception as e:
            rows.append(f"  {domain:8s} ERR: {e}")
    rows.append("")
    rows.append("=== Endpoints — click to test ===")
    for d in ("galaxy", "mars", "adult"):
        _, end_d = kpi_mod.available_range_dates(d)
        if end_d is None:
            rows.append(f"  {d}: no archive data")
            continue
        start_d = end_d - timedelta(days=6)
        qs = f"start={start_d}&end={end_d}"
        rows.append(f'  <a href="/api/kpi/{d}/summary?{qs}">summary {d}</a>')
        rows.append(f'  <a href="/api/kpi/{d}/insights?{qs}">insights {d}</a>')
    rows.append("</pre>")
    return StreamingResponse(iter(["\n".join(rows)]), media_type="text/html")


# Cache buster — 프로세스 시작 시각 (재시작 시에만 변경). 이전엔 매 요청
# time.time() 이라 매초 값이 바뀌어 캐시버스트 의도를 스스로 무력화 + 매 요청
# 디스크 read + replace 반복했음. 시작 시각 상수로 고정하고 HTML 은 1회만 렌더.
_ASSET_V = str(int(time.time()))
_INDEX_HTML: str | None = None


def _render_index() -> str:
    global _INDEX_HTML
    if _INDEX_HTML is None:
        html = (STATIC_DIR / "index.html").read_text()
        for asset in ("style.css", "notion.css", "dashboard.js", "app.js", "i18n.js"):
            html = html.replace(f"/static/{asset}", f"/static/{asset}?v={_ASSET_V}")
        _INDEX_HTML = html
    return _INDEX_HTML


@app.get("/")
async def root() -> Response:
    """Serve index.html with asset URLs version-stamped at startup (cache buster).
    렌더 결과는 프로세스 수명 동안 캐시 — 재시작 시에만 새 버전."""
    return Response(
        content=_render_index(),
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# EDA artifacts (figures, reports) live under /tmp/eda/<session>/. Serve them
# so the chat UI can inline-render charts produced by the eda-figures skill.
EDA_DIR = Path("/tmp/eda")
EDA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/eda-files", StaticFiles(directory=EDA_DIR), name="eda-files")


# Chart PNG path cache: (domain, period_start, period_end, chart_name) → path.
# 같은 요청 반복 시 PNG 재생성 X (matplotlib 0.3-1s 절약).
# cleanup_eda_files() 가 PNG 삭제하면 다음 access 시 자동 invalidate (파일 존재 확인).
_CHART_CACHE: dict[tuple[str, str, str, str], str] = {}
_CHART_CACHE_MAX = 500  # 500개 entry 까지 — 도메인×기간×차트별 ~20개씩 보관 가능

_CHART_PALETTE = ["#d97757", "#5b8dee", "#4dd3c1", "#ec5b8e"]
_CHART_RC = {
    "axes.unicode_minus": False,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white", "savefig.dpi": 160, "savefig.bbox": "tight",
    "axes.titlesize": 14, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.labelcolor": "#555", "xtick.color": "#555", "ytick.color": "#555",
    "axes.edgecolor": "#bbb", "axes.linewidth": 0.8,
}


def _chart_setup() -> Any:
    """matplotlib + Korean font + common rcParams. Returns plt module."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt
    for p in ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
              str(BASE_DIR / "plugins/eda/skills/eda-figures/assets/fonts/malgun.ttf")):
        if Path(p).exists():
            fm.fontManager.addfont(p)
            plt.rcParams["font.family"] = fm.FontProperties(fname=p).get_name()
            break
    plt.rcParams.update(_CHART_RC)
    return plt


def _chart_save(fig, session_id: int, name: str) -> str:
    """Save figure to /tmp/eda/sess_<id>/<name>.png, return embed path."""
    out_dir = EDA_DIR / f"sess_{session_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}.png"
    import matplotlib.pyplot as plt
    plt.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return f"/eda-files/sess_{session_id}/{name}.png"


def _auto_bar_chart(items: list[dict], label_key: str, value_key: str,
                    title: str, session_id: int, name: str) -> str | None:
    """Top-N horizontal bar PNG (highlight top 3)."""
    if not items:
        return None
    try:
        plt = _chart_setup()
        items = items[:10]
        labels = [str(it.get(label_key, ""))[:30] for it in items]
        values = [float(it.get(value_key, 0)) for it in items]
        if not values or max(values) <= 0:
            return None
        fig, ax = plt.subplots(figsize=(9, max(3, len(items) * 0.45)))
        colors = ["#d97757" if i < 3 else "#D8D5CC" for i in range(len(items))]
        bars = ax.barh(range(len(items)), values, color=colors, edgecolor="none")
        ax.set_yticks(range(len(items))); ax.set_yticklabels(labels); ax.invert_yaxis()
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        ax.grid(False)
        vmax = max(values) or 1
        for bar, v in zip(bars, values, strict=False):
            ax.text(bar.get_width() + vmax * 0.01, bar.get_y() + bar.get_height() / 2,
                    f"{int(v):,}" if v == int(v) else f"{v:.2f}",
                    va="center", fontsize=10, color="#333")
        ax.set_xlim(0, vmax * 1.15)
        ax.set_title(title, color="#1a1a1a", loc="left", pad=15)
        return _chart_save(fig, session_id, name)
    except Exception:
        log.exception("bar chart failed")
        return None


def _auto_line_chart(timeseries: list[dict], y_keys: list[str],
                     title: str, session_id: int, name: str) -> str | None:
    """Daily timeseries line PNG."""
    if not timeseries or not y_keys:
        return None
    try:
        plt = _chart_setup()
        dates = [r.get("date", "") for r in timeseries]
        fig, ax = plt.subplots(figsize=(9, 4))
        for i, yk in enumerate(y_keys):
            ys = [float(r.get(yk, 0)) for r in timeseries]
            ax.plot(dates, ys, marker="o", linewidth=2,
                    color=_CHART_PALETTE[i % len(_CHART_PALETTE)], label=yk)
            for x_i, y_i in zip(dates, ys, strict=False):
                ax.text(x_i, y_i, f"{int(y_i):,}", ha="center", va="bottom",
                        fontsize=9, color="#333")
        ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
        ax.grid(False)
        ax.set_title(title, color="#1a1a1a", loc="left", pad=15)
        if len(y_keys) > 1:
            ax.legend(loc="upper left", frameon=False)
        plt.xticks(rotation=30, ha="right")
        return _chart_save(fig, session_id, name)
    except Exception:
        log.exception("line chart failed")
        return None


class SessionCreate(BaseModel):
    title: str = "새 분석"


class ChatRequest(BaseModel):
    message: str


@app.get("/api/kpi/domains")
async def kpi_domains() -> dict[str, Any]:
    return {
        "domains": kpi_mod.domain_meta(),
        "ranges": {d["key"]: kpi_mod.available_range(d["key"]) for d in kpi_mod.domain_meta()},
    }


@app.get("/api/kpi/{domain}/summary")
async def kpi_summary(
    domain: str,
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    content_types: str | None = Query(
        None, description="galaxy/mars multi-select comma list"
    ),
    action_types: str | None = Query(
        None, description="action multi-select comma list (CLICK,PLAY,...)"
    ),
) -> dict[str, Any]:
    if domain not in {d["key"] for d in kpi_mod.domain_meta()}:
        raise HTTPException(status_code=404, detail=f"unknown domain: {domain}")
    try:
        from datetime import date as _date
        start_d = _date.fromisoformat(start)
        end_d = _date.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end < start")
    cts = [c for c in (content_types or "").split(",") if c] or None
    ats = [a for a in (action_types or "").split(",") if a] or None
    # cache miss 시 feather read + ~25 groupby 가 수초 → event loop 블로킹 방지.
    # (pyarrow/pandas 는 C 영역에서 GIL 해제하므로 to_thread 가 실제로 loop 를 풀어줌)
    import asyncio
    result = await asyncio.to_thread(
        kpi_mod.summary, domain, start_d, end_d, content_types=cts, action_types=ats
    )
    # Lazy filter prewarm: 데모 안정 우선으로 비활성화 (CPU 126% 점유 → 페이지
    # 로딩 느려짐). 필터 클릭 시 첫 한 번만 ~30s 계산, 이후 캐시 hit.
    # 다시 켜려면 아래 두 줄 주석 해제.
    # import asyncio as _asyncio
    # _asyncio.create_task(_lazy_prewarm_filters(domain, start_d, end_d))
    return result


@app.get("/api/kpi/{domain}/series")
async def kpi_series(
    domain: str,
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    content_types: str | None = Query(None),
    action_types: str | None = Query(None),
    label: str | None = Query(None, description="single KPI label for modal detail"),
) -> dict[str, Any]:
    if domain not in {d["key"] for d in kpi_mod.domain_meta()}:
        raise HTTPException(status_code=404, detail=f"unknown domain: {domain}")
    try:
        from datetime import date as _date
        start_d = _date.fromisoformat(start)
        end_d = _date.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if end_d < start_d:
        raise HTTPException(status_code=400, detail="end < start")
    cts = [c for c in (content_types or "").split(",") if c] or None
    ats = [a for a in (action_types or "").split(",") if a] or None
    try:
        import asyncio
        return await asyncio.to_thread(
            kpi_mod.series_response,
            domain, start_d, end_d,
            content_types=cts, action_types=ats, label=label,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"unknown KPI label: {label}") from exc


# ── AI insights ─────────────────────────────────────────────────

# Insight prompt → prompts/insight.tmpl (편집 시 자동 재로드)


INSIGHT_MODEL = cfg.INSIGHT_MODEL  # single source: _Settings


def _build_insight_prompt(summary: dict, series: dict) -> str:
    lines = [
        f"도메인: {summary['label']}",
        f"기간: {summary['start']} ~ {summary['end']}",
    ]
    if summary.get("content_types"):
        lines.append(f"콘텐츠 필터: {', '.join(summary['content_types'])}")
    lines.append("")
    lines.append("## KPI 요약 (기간 전체)")
    for k in summary["kpis"]:
        v = k["value"]
        fmt = k["fmt"]
        if fmt == "pct":
            disp = f"{v * 100:.2f}%"
        elif fmt == "f2":
            disp = f"{v:.3f}"
        else:
            disp = f"{int(v):,}"
        lines.append(f"- {k['label']}: {disp}")
    lines.append("")
    lines.append("## 일자별 추이 (KST)")
    dates = series.get("dates", [])
    fmts = series.get("fmts", {})
    for label, vals in series.get("series", {}).items():
        fmt = fmts.get(label, "int")
        if fmt == "pct":
            disp = " ".join(f"{v * 100:.2f}%" for v in vals)
        elif fmt == "f2":
            disp = " ".join(f"{v:.2f}" for v in vals)
        else:
            disp = " ".join(f"{int(v):,}" for v in vals)
        lines.append(f"- {label}: [{disp}]")
    if dates:
        lines.append(f"\ndates 순서: {' / '.join(dates)}")
    return "\n".join(lines)


async def _generate_insights(domain: str, start_d, end_d, cts: list[str] | None) -> dict[str, Any]:
    import asyncio
    summary = await asyncio.to_thread(kpi_mod.summary, domain, start_d, end_d, content_types=cts)
    series = await asyncio.to_thread(
        kpi_mod.series_response, domain, start_d, end_d, content_types=cts
    )
    prompt = _build_insight_prompt(summary, series)

    options = ClaudeAgentOptions(
        model=INSIGHT_MODEL,
        system_prompt=_prompts.render("insight"),
        max_turns=1,
        permission_mode="bypassPermissions",
    )
    chunks: list[str] = []
    deadline = time.time() + INSIGHT_TIMEOUT_S
    try:
        async for msg in query(prompt=prompt, options=options):
            if time.time() > deadline:
                log.warning("Insight generation timeout (%ds)", INSIGHT_TIMEOUT_S)
                return {"bullets": [], "error": "LLM 타임아웃"}
            cls = type(msg).__name__
            if cls == "AssistantMessage":
                for block in getattr(msg, "content", []) or []:
                    if text := getattr(block, "text", None):
                        chunks.append(text)
            elif cls == "ResultMessage":
                break
    except Exception:
        log.exception("Insight generation failed")
        return {"bullets": [], "error": "LLM 호출 실패"}

    raw = "".join(chunks).strip()
    import re as _re
    m = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if not m:
        return {"bullets": [], "error": "JSON 파싱 실패", "raw": raw[:300]}
    try:
        parsed = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"bullets": [], "error": "JSON 파싱 실패", "raw": raw[:300]}
    bullets = parsed.get("bullets", [])
    if not isinstance(bullets, list):
        bullets = []
    bullets = [str(b) for b in bullets[:8]]
    # Lightweight self-critique: 중복 phrase / 빈 인사이트 / 같은 문구 반복 제거
    bullets = _filter_insights(bullets)
    return {"bullets": bullets}


# 반복되는 cliché — 사용자 피드백 ("같은 phrase 반복 금지") 기반
_CLICHE_PATTERNS = ("압도적 1위", "압도적인 1위", "독보적", "단연")


def _filter_insights(bullets: list[str]) -> list[str]:
    """Drop empty / duplicate / cliché-heavy bullets. Keep up to 4."""
    seen: set[str] = set()
    filtered: list[str] = []
    cliche_count = 0
    for b in bullets:
        b = b.strip()
        if not b or len(b) < 10:
            continue
        # 같은 첫 15자 시작은 중복 간주
        key = b[:15]
        if key in seen:
            continue
        seen.add(key)
        # cliche 는 최대 1개만 허용
        if any(p in b for p in _CLICHE_PATTERNS):
            cliche_count += 1
            if cliche_count > 1:
                continue
        filtered.append(b)
        if len(filtered) >= 4:
            break
    return filtered


@app.get("/api/kpi/{domain}/insights")
async def kpi_insights(
    domain: str,
    start: str = Query(...),
    end: str = Query(...),
    content_types: str | None = Query(None),
    force: bool = Query(False, description="cache 무시하고 재생성"),
) -> dict[str, Any]:
    if domain not in {d["key"] for d in kpi_mod.domain_meta()}:
        raise HTTPException(status_code=404, detail=f"unknown domain: {domain}")
    try:
        from datetime import date as _date
        start_d = _date.fromisoformat(start)
        end_d = _date.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cts = [c for c in (content_types or "").split(",") if c] or None
    cts_str = ",".join(cts or [])

    # DB cache check
    if not force:
        async with db_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT bullets, model, elapsed_ms, created_at FROM kpi_insights "
                "WHERE domain=$1 AND start_date=$2 AND end_date=$3 AND content_types=$4",
                domain, start_d, end_d, cts_str,
            )
        if row:
            return {
                "bullets": json.loads(row["bullets"]) if isinstance(row["bullets"], str) else row["bullets"],
                "model": row["model"],
                "elapsed_ms": row["elapsed_ms"],
                "cached": True,
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            }

    import time as _t
    t0 = _t.time()
    result = await _generate_insights(domain, start_d, end_d, cts)
    result["elapsed_ms"] = int((_t.time() - t0) * 1000)
    result["model"] = INSIGHT_MODEL

    # Persist to DB (only if bullets generated successfully)
    if result.get("bullets"):
        async with db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO kpi_insights(domain, start_date, end_date, content_types, "
                "bullets, model, elapsed_ms) VALUES($1,$2,$3,$4,$5::jsonb,$6,$7) "
                "ON CONFLICT (domain, start_date, end_date, content_types) DO UPDATE "
                "SET bullets=EXCLUDED.bullets, model=EXCLUDED.model, "
                "    elapsed_ms=EXCLUDED.elapsed_ms, created_at=NOW()",
                domain, start_d, end_d, cts_str,
                json.dumps(result["bullets"]), result["model"], result["elapsed_ms"],
            )
    return result


@app.post("/api/sessions")
async def create_session(req: SessionCreate) -> dict[str, Any]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO sessions(title) VALUES($1) RETURNING id, title, created_at",
            req.title,
        )
    return dict(row)


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, title, created_at, updated_at "
            "FROM sessions ORDER BY updated_at DESC LIMIT 50"
        )
    return [dict(r) for r in rows]


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: int) -> dict[str, Any]:
    """Delete a session and its messages (CASCADE). EDA artifacts under
    /tmp/eda/* are not tied to session_id so we leave them alone."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM sessions WHERE id=$1 RETURNING id",
            session_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="session not found")
    return {"id": row["id"], "deleted": True}


@app.get("/api/sessions/{session_id}/messages")
async def get_messages(session_id: int) -> list[dict[str, Any]]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id=$1 ORDER BY id LIMIT 500",
            session_id,
        )
    return [dict(r) for r in rows]


# Gateway prompt → prompts/gateway.tmpl


GATEWAY_MODEL = cfg.GATEWAY_MODEL  # single source: _Settings
# OAuth direct + Haiku — subprocess CLI 우회로 turn 낭비 X, Sonnet 5h rate-limit 회피.
FAST_LEAD_MODEL = cfg.FAST_LEAD_MODEL  # single source: _Settings

# query() async-for 가 SDK subprocess hang 시 무한 대기하지 않도록 wall-clock 상한.
# slow-track(300s deadline) 과 동일 패턴 — 메시지 사이에서만 체크.
GATEWAY_TIMEOUT_S = int(os.environ.get("MOCHA_GATEWAY_TIMEOUT_S", "30"))
INSIGHT_TIMEOUT_S = int(os.environ.get("MOCHA_INSIGHT_TIMEOUT_S", "60"))

# Note: output_format (Anthropic structured output) 적용 시도했으나 schema enum
# 강제가 모델 reasoning 흐름을 깨뜨려 NARROW 질문 ("ml1m TOP 10") 도 broad_eda +
# unknown 으로 fallback 분류 (3/3) → Lead 헛수고 → 107s 회귀. 자연어 JSON 유지.


# Keyword 기반 사전 분류 — 명확한 매칭이면 LLM 호출 skip (13s 절약).
_DOMAIN_KW = {
    "adult":   ["성인", "adult", "rec_adult", "nsfw", "성인관"],
    "watcha_main": ["왓챠", "mars", "graph_modeling", "user_bert", "next_watch"],
    "pedia":   ["피디아", "갤럭시", "galaxy", "rec_galaxy", "별점", "보싶"],
    "ml_1m":   ["ml-1m", "ml_1m", "movielens"],
}
_INTENT_KW = [
    ("narrow_top_n",        ["top", "탑", "인기", "가장 많이", "최다", "큰손", "랭킹", "1위", "최대", "베스트", "best", "순위"]),
    ("narrow_distribution", ["분포", "추이", "일별", "시간대", "비율"]),
    ("narrow_count",        ["얼마", "몇 ", "총합", " dau", " cvr", " arpu", "평균"]),
    ("interpretive_qa",     ["왜 ", "이유", "어떻게", "차이", "관계", "의미", "분석해", "조회"]),
    ("broad_eda",           ["전반", "전체 데이터", "eda", "데이터 특성", "종합"]),
    ("ab_test",             ["a/b", "ab 테스트", "실험 결과", "그룹 비교"]),
    ("report",              ["리포트", "마크다운", "발표 자료"]),
    ("notion",              ["노션", "notion"]),
    ("small_talk",          ["안녕", "도와줘", "뭐 할 수 있어"]),
]
_FAST_INTENTS = {"narrow_top_n", "narrow_distribution", "narrow_count",
                 "interpretive_qa", "notion", "small_talk",
                 # broad_eda 도 fast 로 — KPI inline 풍부함으로 처리.
                 # slow track 은 Sonnet rate-limit + subprocess hang 위험 → 발표 안정성 우선.
                 "broad_eda"}

# 시각화 요청 keywords — fast track 으로 분류돼도 강제로 slow 로 escalate
# (chart 생성은 Bash + matplotlib 필요 → fast 의 allowed_tools=[] 로는 불가).
_VIZ_KW = ["시각화", "차트", "그래프", "plot", "visualize", "chart", "그려"]


def _extract_period_days(question: str) -> int | None:
    """질문에서 기간 표현 추출 → 일수.  매칭 안되면 None (default 7일 사용)."""
    import re as _re
    q = question.lower()
    # "최근 N일", "N일간", "N일치"
    m = _re.search(r"(\d+)\s*일", q)
    if m and "일" not in q.split(m.group(0))[0][-3:]:  # avoid "1일전" 류
        return int(m.group(1))
    # "1년", "근 1년", "지난 1년", "1년간", "1년치"
    if _re.search(r"\b1\s*년|일\s*년|한\s*해|1년치|1년간|근\s*1년|지난\s*1년", q) or "1년" in q:
        return 365
    if _re.search(r"6\s*개월|반\s*년|6개월", q):
        return 180
    if _re.search(r"3\s*개월|3개월|분기", q):
        return 90
    if _re.search(r"한\s*달|1\s*개월|1개월|이번\s*달|지난\s*달|이번달|지난달", q):
        return 30
    if _re.search(r"1\s*주|이번\s*주|지난\s*주|일주일|1주일", q):
        return 7
    if "어제" in q or "오늘" in q:
        return 1
    return None


def _classify_local(question: str) -> dict[str, Any] | None:
    q = question.lower()
    domain = "unknown"
    for d, kws in _DOMAIN_KW.items():
        if any(k in q for k in kws):
            domain = d
            break
    intent = None
    for name, kws in _INTENT_KW:
        if any(k in q for k in kws):
            intent = name
            break
    if intent is None:
        return None  # fallback to LLM gateway
    needs_viz = any(k in q for k in _VIZ_KW)
    # Charts now auto-generated in backend (fast track) — viz query stays fast.
    track = "fast" if intent in _FAST_INTENTS else "slow"
    result = {"track": track, "intent": intent, "domain": domain,
              "summary": question.strip()[:80]}
    if needs_viz:
        result["needs_viz"] = True
    period = _extract_period_days(question)
    if period:
        result["period_days"] = period
    return result


async def gateway_classify(question: str) -> dict[str, Any]:
    """1) Keyword 매칭으로 사전 분류 (즉시) → 2) 매칭 실패 시 LLM 분류 fallback.

    매 query 시 ~6-9초 / ~$0.005. system_prompt 의 "JSON 만 출력" 지시로 안정성 확보.
    """
    # 1) Local keyword classifier — 명확한 케이스는 즉시 분류
    local = _classify_local(question)
    if local:
        return local

    # 2) LLM fallback — 모호한 질문만
    options = ClaudeAgentOptions(
        model=GATEWAY_MODEL,
        system_prompt=_prompts.render("gateway"),
        max_turns=1,
        permission_mode="bypassPermissions",
    )
    chunks: list[str] = []
    deadline = time.time() + GATEWAY_TIMEOUT_S
    try:
        async for msg in query(prompt=question, options=options):
            if time.time() > deadline:
                log.warning("Gateway classify timeout (%ds) — slow track default", GATEWAY_TIMEOUT_S)
                return {"track": "slow", "intent": "broad_eda",
                        "summary": "분류 타임아웃 — slow track default"}
            cls = type(msg).__name__
            if cls == "AssistantMessage":
                for block in getattr(msg, "content", []) or []:
                    if text := getattr(block, "text", None):
                        chunks.append(text)
            elif cls == "ResultMessage":
                break
    except Exception:
        log.exception("Gateway classify failed")
        return {"track": "slow", "intent": "broad_eda", "summary": "분류 실패 — slow track default"}

    raw = "".join(chunks).strip()
    # JSON 추출
    import re as _re
    m = _re.search(r"\{.*\}", raw, _re.DOTALL)
    if m:
        try:
            parsed = json.loads(m.group(0))
            # 최소 필드 검증 + default
            if parsed.get("track") in ("fast", "slow") and "intent" in parsed:
                parsed.setdefault("summary", "")
                parsed.setdefault("domain", "unknown")
                return parsed
        except json.JSONDecodeError:
            pass
    log.warning("Gateway returned unparseable response: %r", raw[:200])
    return {"track": "slow", "intent": "broad_eda", "domain": "unknown", "summary": "분류 결과 파싱 실패"}


async def _stream_response(
    session_id: int, message: str, request: Request | None = None
) -> AsyncIterator[str]:
    _session_id_ctx.set(session_id)
    async with db_pool.acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT id, sdk_session_id FROM sessions WHERE id=$1",
            session_id,
        )
        if not sess:
            yield _sse_error("session_not_found", "session not found")
            return

        await conn.execute(
            "INSERT INTO messages(session_id, role, content) VALUES($1, 'user', $2)",
            session_id,
            message,
        )

    # Gateway — Haiku 1턴으로 fast/slow + intent + domain 분류
    yield _sse("gateway", {"status": "classifying"})
    classification = await gateway_classify(message)

    # Follow-up 질문에서 도메인 미언급 → 같은 세션의 직전 user message 에서 도메인 추론.
    # ("1년치로 조회해줘", "다시 보여줘" 같은 짧은 후속 요청 대응)
    if classification.get("domain") == "unknown":
        async with db_pool.acquire() as conn:
            prev = await conn.fetchrow(
                "SELECT content FROM messages WHERE session_id=$1 AND role='user' "
                "AND id < (SELECT max(id) FROM messages WHERE session_id=$1) "
                "ORDER BY id DESC LIMIT 1",
                session_id,
            )
        if prev:
            prev_cls = _classify_local(prev["content"])
            if prev_cls and prev_cls.get("domain") != "unknown":
                classification["domain"] = prev_cls["domain"]
                classification["summary"] = (
                    f"[이전 컨텍스트 → {prev_cls['domain']}] {classification.get('summary', '')}"
                )

    yield _sse("gateway", {"status": "classified", **classification})

    # Gateway 결정 domain 만 SYSTEM_PROMPT 에 주입 (다른 도메인 행 제거 → token ~40% 절감)
    # classification 도메인 ↔ KPI 도메인 매핑 (gateway: pedia/watcha_main/adult ↔ kpi: galaxy/mars/adult)
    _DOMAIN_MAP = {"pedia": "galaxy", "watcha_main": "mars", "adult": "adult"}
    domain = _DOMAIN_MAP.get(classification.get("domain", "unknown"), "unknown")
    system_prompt = build_system_prompt(domain)

    # Gateway hint passed to Lead (telegraphic — internal logic, output stays Korean)
    viz_note = "  VIZ_REQUIRED: matplotlib chart inline (PNG → /tmp/eda/.../*.png → ![](path)).\n" if classification.get("needs_viz") else ""
    track_hint = (
        f"\n## Gateway: track={classification['track']} "
        f"intent={classification['intent']} q={classification.get('summary', '')}\n"
        f"{viz_note}"
    )
    # fast 는 단순 통계 + 시각화 1-2장 (Bash 1 + 답변) → 12 turn.
    # slow 는 broad/A/B test (Bash 5-8 + figures + report) → 30 turn.
    # Note: fast track 에서 tools=["Bash","Read","Write"] 로 제한 시도했으나
    # bypassPermissions 모드에서는 인자가 행동을 막지 못함 (Glob 호출됨). 롤백.
    is_fast = classification["track"] == "fast"
    track_max_turns = 8 if is_fast else 30
    lead_model = FAST_LEAD_MODEL if is_fast else MODEL

    # fast track + 알려진 도메인 → KPI summary 를 pre-fetch 해서 prompt 에 inline.
    # → Lead 가 curl tool 호출 round-trip 1회 절약 + skills/plugin 로딩도 skip.
    fast_kpi_inline = None
    # KPI summary 동기 fetch 시간이 기간에 비례. cap 자체는 큼 (default 1000) —
    # archive `available_range` 로 자동 clamp 되니까 사실상 archive 끝까지 cover.
    # 더 짧게 제한하려면 env `MOCHA_FAST_INLINE_MAX_DAYS`.
    MAX_DAYS = cfg.FAST_INLINE_MAX_DAYS
    if is_fast and domain in ("galaxy", "mars", "adult"):
        try:
            from datetime import timedelta
            min_d, end_d = kpi_mod.available_range_dates(domain)
            if end_d is None:
                # 아카이브 데이터 없음 (CI/미마운트) → inline skip, tool-call fallback.
                raise RuntimeError(f"no archive data for {domain}")
            requested_days = max(1, int(classification.get("period_days", 7)))
            actual_days = min(requested_days, MAX_DAYS)
            start_d = max(end_d - timedelta(days=actual_days - 1), min_d)
            # SSE progress — 사용자에게 "지금 어디까지 진행됐는지" 보여주려는 의도.
            # KPI fetch 가 cache miss 일 때만 몇 초 이상 걸리고, hit 면 ms 단위로 끝남.
            t_fetch = time.time()
            import asyncio as _asyncio
            yield _sse("status", {
                "stage": "kpi_fetch",
                "label": f"{domain.upper()} {actual_days}일 KPI 집계 중",
            })
            kpi_full = await _asyncio.to_thread(kpi_mod.summary, domain, start_d, end_d, None, None)
            fetch_ms = int((time.time() - t_fetch) * 1000)
            log.info(f"[fast-inline] {domain} {start_d}~{end_d} ({actual_days}d) fetched in {fetch_ms}ms")
            yield _sse("status", {
                "stage": "kpi_done",
                "label": f"KPI 집계 완료 ({fetch_ms}ms)",
                "elapsed_ms": fetch_ms,
            })
            # 큰 시계열 / 메타 필드 제거 (top-N + 핵심 KPI + files_read + timeseries 만 남김)
            # timeseries 는 추이/distribution 질문 답변에 필수 → inline 유지.
            DROP = {"hourly_activity", "pareto_curve",
                    "rating_distribution", "available_content_types",
                    "available_action_types", "supports",
                    "content_types", "action_types"}
            trimmed = {k: v for k, v in kpi_full.items() if k not in DROP}
            fast_kpi_inline = {
                "period": f"{start_d} ~ {end_d}",
                "source_path": {
                    "galaxy": f"{kpi_mod.ARCHIVE}/rec_galaxy/behavior_logs/",
                    "mars":   f"{kpi_mod.ARCHIVE}/user_bert/behavior_logs2/train/",
                    "adult":  f"{kpi_mod.ARCHIVE}/rec_adult/behavior_logs/",
                }.get(domain, "—"),
                "period_days": actual_days,
                "requested_days": requested_days,
                "capped": requested_days > actual_days,
                "data": trimmed,
            }
        except RuntimeError as exc:
            # 데이터 부재 등 예상된 skip — traceback 없이 조용히 fallback.
            log.info("fast-track inline skipped (%s); using tool-call mode", exc)
        except Exception:
            log.exception("fast-track KPI pre-fetch failed; falling back to tool-call mode")

    if fast_kpi_inline:
        # OAuth direct path: bypass claude_agent_sdk + subprocess CLI.
        # → 0 spawn overhead, ~5-10s target. No API key → no extra cost.
        # Internal logic in English (token-efficient); output forced to Korean.
        cap_note = ""
        if fast_kpi_inline.get("capped"):
            cap_note = (
                f"CAP: asked {fast_kpi_inline['requested_days']}d, gave {fast_kpi_inline['period_days']}d. "
                f"Say '최근 {fast_kpi_inline['period_days']}일 기준', suggest dashboard/BQ for longer.\n"
            )
        # Auto-charts — pick 1 by query intent FIRST, then generate only that PNG.
        # (이전엔 7-9개 다 생성 후 1개만 쓰는 낭비; cold matplotlib + 다중 생성 → ~25s 손실)
        d = fast_kpi_inline['data']
        rev = d.get("revenue") or {}
        top_payers = rev.get("top_payers", []) if isinstance(rev, dict) else []
        ts = d.get("timeseries", [])

        def _titled(items: list[dict]) -> list[dict]:
            return [{**it, "_lbl": (it.get("title") or it.get("content"))} for it in (items or [])]

        # chart_name → (kind, args) ; lazy — not executed until picked
        bar_specs: dict[str, tuple[list[dict], str, str, str]] = {
            "top_genres":           (d.get("top_genres", []),                "name",    "events",     f"{domain.upper()} 장르별 인기 TOP 10"),
            "top_contents":         (_titled(d.get("top_contents", [])),     "_lbl",    "events",     f"{domain.upper()} 콘텐츠 TOP 10 (이벤트 기준)"),
            "top_directors":        (d.get("top_directors", []),             "label",   "count",      f"{domain.upper()} 인기 감독 TOP 10"),
            "top_actors":           (d.get("top_actors", []),                "label",   "count",      f"{domain.upper()} 인기 배우 TOP 10"),
            "top_revenue_contents": (_titled(d.get("top_revenue_contents", [])),"_lbl",  "revenue",   f"{domain.upper()} 매출 TOP 10"),
            "top_rated_contents":   (_titled(d.get("top_rated_contents", [])),"_lbl",   "avg_rating", f"{domain.upper()} 평점 높은 콘텐츠 TOP 10"),
            "top_payers":           (top_payers,                             "user_id", "revenue",    f"{domain.upper()} 최다 결제 유저 TOP 10"),
        }
        line_specs: dict[str, tuple[list[str], str]] = {
            "ts_users":  (["users"],  f"{domain.upper()} 일자별 활동 유저 추이"),
            "ts_events": (["events"], f"{domain.upper()} 일자별 이벤트 수 추이"),
        }

        def _available(name: str) -> bool:
            if name in bar_specs:
                items, *_ = bar_specs[name]
                return bool(items)
            if name in line_specs:
                return bool(ts)
            return False

        def _pick_chart_name(q: str) -> str | None:
            ql = q.lower()
            rules = [
                (("추이", "trend", "시계열", "일자별", "일별", "변화"), ["ts_users", "ts_events"]),
                (("결제 유저", "큰손", "결제한", "payer", "결제하"), ["top_payers"]),
                (("매출", "수익", "revenue"), ["top_revenue_contents"]),
                (("감독", "director"), ["top_directors"]),
                (("배우", "actor"), ["top_actors"]),
                (("평점 높", "베스트", "최고 평점", "best", "rated"), ["top_rated_contents"]),
                (("장르", "genre"), ["top_genres"]),
                (("콘텐츠", "영화", "작품", "content"), ["top_contents", "top_rated_contents"]),
            ]
            for kws, names in rules:
                if any(k in ql for k in kws):
                    for n in names:
                        if _available(n):
                            return n
            # fallback: any available bar chart
            for n in bar_specs:
                if _available(n):
                    return n
            return None

        picked_chart = _pick_chart_name(message)
        picked_chart_path: str | None = None
        picked_chart_alt: str = ""
        if picked_chart:
            cache_key = (domain, fast_kpi_inline["period"], picked_chart, str(session_id))
            # Note: session_id 포함 — 다른 sessions 의 PNG 파일이 cleanup 으로 사라져도
            # 자기 session 내 재사용은 hit. (cross-session caching 은 cleanup race condition 위험)
            cached = _CHART_CACHE.get(cache_key)
            if cached:
                fs_path = Path("/tmp" + cached.replace("/eda-files", "/eda"))
                if fs_path.exists():
                    picked_chart_path = cached
                    if _PROM_AVAILABLE:
                        try: CHART_CACHE_HIT.labels(outcome="hit").inc()
                        except Exception: pass
                else:
                    if _PROM_AVAILABLE:
                        try: CHART_CACHE_HIT.labels(outcome="stale").inc()
                        except Exception: pass
            if not picked_chart_path:
                if picked_chart in bar_specs:
                    items, lkey, vkey, title_ = bar_specs[picked_chart]
                    picked_chart_path = _auto_bar_chart(items, lkey, vkey, title_, session_id, picked_chart)
                    picked_chart_alt = title_
                elif picked_chart in line_specs:
                    y_keys, title_ = line_specs[picked_chart]
                    picked_chart_path = _auto_line_chart(ts, y_keys, title_, session_id, picked_chart)
                    picked_chart_alt = title_
                if picked_chart_path:
                    if len(_CHART_CACHE) >= _CHART_CACHE_MAX:
                        _CHART_CACHE.pop(next(iter(_CHART_CACHE)))
                    _CHART_CACHE[cache_key] = picked_chart_path
                    if _PROM_AVAILABLE:
                        try: CHART_CACHE_HIT.labels(outcome="miss").inc()
                        except Exception: pass
            else:
                # cache hit → alt 도 spec 에서 채움
                if picked_chart in bar_specs:
                    picked_chart_alt = bar_specs[picked_chart][3]
                elif picked_chart in line_specs:
                    picked_chart_alt = line_specs[picked_chart][1]
        # KPI JSON minified — saves ~20-30% input tokens.
        kpi_json = json.dumps(fast_kpi_inline['data'], ensure_ascii=False, separators=(",", ":"))
        files_str = ", ".join(fast_kpi_inline['data'].get('files_read', []) or [])
        # Backend가 1개 chart 선택 — LLM은 이 chart 만 inline. 다른 chart 보여주지 않음.
        # alt 텍스트 = chart 한국어 제목 (스크린리더/접근성).
        charts_str = (f"  - `![{picked_chart_alt}]({picked_chart_path})`"
                      if picked_chart_path else "  (none)")
        # Prompt → prompts/fast_panda.tmpl  (편집 시 mtime-watch 로 자동 재로드)
        fast_system = _prompts.render(
            "fast_panda",
            DOMAIN=domain.upper(),
            PERIOD=fast_kpi_inline["period"],
            PERIOD_DAYS=fast_kpi_inline["period_days"],
            INTENT=classification["intent"],
            QUERY=classification.get("summary", ""),
            SOURCE_PATH=fast_kpi_inline["source_path"],
            FILES_LIST=fast_kpi_inline["data"].get("files_read", []),
            CAP_NOTE=cap_note,
            KPI_JSON=kpi_json,
            CHARTS=charts_str,
            FILES_STR=files_str,
        )
        # Conversation history — 직전 user/assistant 4개 turn (multi-turn context)
        history: list[dict] = []
        try:
            async with db_pool.acquire() as conn:
                hist_rows = await conn.fetch(
                    "SELECT role, content FROM messages WHERE session_id=$1 "
                    "AND id < (SELECT max(id) FROM messages WHERE session_id=$1) "
                    "ORDER BY id DESC LIMIT 4",
                    session_id,
                )
            history = list(reversed([{"role": r["role"], "content": r["content"]} for r in hist_rows]))
        except Exception:
            log.exception("history fetch failed")

        full_text = []
        usage_info = None
        # LLM streaming 시작 시점 기록 → 첫 토큰까지의 latency 를 사용자에게 표시.
        t_llm = time.time()
        yield _sse("status", {"stage": "llm_start", "label": f"답변 생성 중 ({lead_model.split('-')[1]})"})
        first_token_ms: int | None = None
        async for kind, payload_ in stream_oauth_completion(
            model=lead_model, system=fast_system, user_msg=message, max_tokens=2048,
            history=history or None,
        ):
            if request is not None and await request.is_disconnected():
                log.info("client disconnected mid-stream — aborting LLM stream")
                break
            if kind == "text":
                if first_token_ms is None:
                    first_token_ms = int((time.time() - t_llm) * 1000)
                    yield _sse("status", {
                        "stage": "llm_first_token",
                        "label": f"첫 토큰 ({first_token_ms}ms)",
                        "elapsed_ms": first_token_ms,
                    })
                full_text.append(payload_)
                yield _sse("text", {"text": payload_})
            elif kind == "done":
                try:
                    usage_info = json.loads(payload_)
                except json.JSONDecodeError:
                    usage_info = None
            elif kind == "error":
                yield _sse_error("llm_stream_failed", payload_)
                errored = True
                break
        # 통합 답변 DB persist
        if full_text:
            assistant_text = "".join(full_text)
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO messages(session_id, role, content) VALUES($1, 'assistant', $2)",
                    session_id, assistant_text,
                )
        # Token usage 누적 (subscription quota 추세 모니터링)
        if usage_info:
            try:
                await _record_token_usage(lead_model, usage_info)
            except Exception:
                log.exception("token_usage persist failed (continuing)")
        # cost = 0 (subscription quota — API 호출 X)
        yield _sse("done", {"cost_usd": 0.0, "via": "oauth_direct", "usage": usage_info})
        return
    elif is_fast:
        # Fast track but no KPI domain (small_talk / interpretive_qa / unknown).
        # OAuth-direct generic path — keeps root-user dev env working (claude-agent-sdk
        # subprocess refuses bypassPermissions under sudo). If the user actually wants
        # data, the model is told to ask which domain (mars / galaxy / adult).
        fast_system = (
            "Watcha 데이터 분석가. 한국어로 짧고 명확하게 답한다. "
            "데이터 질문처럼 보이면 어느 도메인 (왓챠 mars / 왓챠피디아 galaxy / 성인+ adult) "
            "인지 한 줄로 되묻는다. 일반 인사·잡담은 한두 문장으로 응답."
        )
        full_text: list[str] = []
        usage_info = None
        t_llm = time.time()
        yield _sse("status", {"stage": "llm_start", "label": "답변 생성 중"})
        first_token_ms: int | None = None
        async for kind, payload_ in stream_oauth_completion(
            model=lead_model, system=fast_system, user_msg=message, max_tokens=1024,
            history=None,
        ):
            if request is not None and await request.is_disconnected():
                log.info("client disconnected mid-stream — aborting LLM stream")
                break
            if kind == "text":
                if first_token_ms is None:
                    first_token_ms = int((time.time() - t_llm) * 1000)
                    yield _sse("status", {
                        "stage": "llm_first_token",
                        "label": f"첫 토큰 ({first_token_ms}ms)",
                        "elapsed_ms": first_token_ms,
                    })
                full_text.append(payload_)
                yield _sse("text", {"text": payload_})
            elif kind == "done":
                try:
                    usage_info = json.loads(payload_)
                except json.JSONDecodeError:
                    usage_info = None
            elif kind == "error":
                yield _sse_error("llm_stream_failed", payload_)
                break
        if full_text:
            assistant_text = "".join(full_text)
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO messages(session_id, role, content) VALUES($1, 'assistant', $2)",
                    session_id, assistant_text,
                )
        if usage_info:
            try:
                await _record_token_usage(lead_model, usage_info)
            except Exception:
                log.exception("token_usage persist failed (continuing)")
        yield _sse("done", {"cost_usd": 0.0, "via": "oauth_direct_generic", "usage": usage_info})
        return
    else:
        options = ClaudeAgentOptions(
            cwd=str(BASE_DIR),
            plugins=[{"type": "local", "path": str(PLUGIN_DIR)}],
            skills="all",
            permission_mode="bypassPermissions",
            model=lead_model,
            system_prompt=system_prompt + track_hint,
            max_turns=track_max_turns,
            max_budget_usd=MAX_BUDGET_USD,
            resume=sess["sdk_session_id"] if sess["sdk_session_id"] else None,
        )

    assistant_chunks: list[str] = []
    new_sdk_session: str | None = None
    errored = False
    # Slow track 안정성 가드:
    #  - 5분 hard timeout (subprocess hang 방지)
    #  - tool message 100개 초과 시 infinite-loop 의심 → abort
    slow_deadline = time.time() + 300
    tool_msg_count = 0
    log.info("[slow-track] starting query (deadline 300s)")

    try:
        async for msg in query(prompt=message, options=options):
            if request is not None and await request.is_disconnected():
                log.info("client disconnected mid-stream — aborting slow-track query")
                errored = True
                break
            if time.time() > slow_deadline:
                yield _sse_error(
                    "slow_track_timeout",
                    "분석이 5분을 초과하여 중단됨. 더 좁은 질문으로 다시 시도.",
                )
                errored = True
                break
            cls = type(msg).__name__

            if cls == "SystemMessage":
                data = getattr(msg, "data", None) or {}
                sid = data.get("session_id")
                if sid:
                    new_sdk_session = sid

            elif cls == "AssistantMessage":
                for block in getattr(msg, "content", []) or []:
                    text = getattr(block, "text", None)
                    if text:
                        assistant_chunks.append(text)
                        yield _sse("text", {"text": text})
                        continue
                    tool_name = getattr(block, "name", None)
                    if tool_name:
                        tool_msg_count += 1
                        if tool_msg_count > 100:
                            yield _sse_error(
                                "slow_track_runaway",
                                "tool 호출이 100회를 초과해 무한 루프 의심 — 중단",
                            )
                            errored = True
                            break
                        # Truncated tool input for timing/debug; long Bash
                        # commands get clipped to keep the SSE frame small.
                        tool_input = getattr(block, "input", None) or {}
                        preview: dict[str, Any] = {}
                        for k, v in tool_input.items():
                            s = str(v)
                            preview[k] = s if len(s) <= 200 else s[:200] + "…"
                        yield _sse("tool", {"name": tool_name, "input": preview})

            elif cls == "ResultMessage":
                cost = getattr(msg, "total_cost_usd", None)
                subtype = getattr(msg, "subtype", "success")
                is_error = bool(getattr(msg, "is_error", False))
                if is_error or subtype != "success":
                    # budget 초과, max_turns 초과, API 에러 등 — 종료 사유 안내
                    errored = True
                    reason = subtype if subtype != "success" else "API/내부 에러"
                    yield _sse_error(
                        "agent_abnormal_exit",
                        f"분석이 비정상 종료됨 — {reason}",
                        subtype=subtype, is_error=is_error, cost_usd=cost,
                    )
                else:
                    yield _sse("done", {"cost_usd": cost})
                break

            elif cls == "RateLimitEvent":
                yield _sse("rate_limit", {"message": str(msg)})

    except Exception as exc:
        log.exception("Agent query failed")
        errored = True
        yield _sse_error("internal", str(exc), exc_type=type(exc).__name__)

    assistant_text = "".join(assistant_chunks).strip()
    if not assistant_text:
        assistant_text = "(중단됨)" if errored else "(빈 응답)"
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages(session_id, role, content) VALUES($1, 'assistant', $2)",
            session_id,
            assistant_text,
        )
        # budget/max_turns 초과 등 errored 시: 깨진 SDK state 가 다음 turn 으로 누수되지 않게
        # sdk_session_id 를 NULL 로 리셋. 다음 호출은 fresh session 시작.
        if errored:
            await conn.execute(
                "UPDATE sessions SET sdk_session_id=NULL, updated_at=NOW() WHERE id=$1",
                session_id,
            )
        elif new_sdk_session:
            await conn.execute(
                "UPDATE sessions SET sdk_session_id=$1, updated_at=NOW() WHERE id=$2",
                new_sdk_session,
                session_id,
            )
        else:
            await conn.execute(
                "UPDATE sessions SET updated_at=NOW() WHERE id=$1",
                session_id,
            )


def _sse(event_type: str, payload: dict[str, Any]) -> str:
    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


def _sse_error(code: str, message: str, **extra: Any) -> str:
    """Structured error SSE event — {type:error, code, message, ...}."""
    return _sse("error", {"code": code, "message": message, "error": message, **extra})


@app.post("/api/sessions/{session_id}/chat")
async def chat(session_id: int, req: ChatRequest, request: Request) -> StreamingResponse:
    if not db_pool:
        raise HTTPException(status_code=503, detail="db unavailable")
    return StreamingResponse(
        _stream_response(session_id, req.message, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# /archive/mocha/sessions/<date>/ 에 마크다운으로 영구 저장.
# 데모/리뷰 자료로 모아두는 용도. mocha-owned 데이터는 `/archive/mocha/` 하위로 격리.
_ARCHIVE_ROOT = Path(os.environ.get("MOCHA_ARCHIVE_ROOT", "/archive/mocha/sessions"))


def _session_to_markdown(sess, rows) -> str:
    """세션 + 메시지 rows → markdown 문자열 (archive/export 공통 포맷)."""
    lines = [
        f"# {sess['title']}",
        "",
        f"- 세션 #{sess['id']}",
        f"- 시작: {sess['created_at'].isoformat()}",
        f"- 메시지: {len(rows)}",
        "",
        "---",
        "",
    ]
    for r in rows:
        role_label = "🧑 사용자" if r["role"] == "user" else "🤖 MOCHA"
        lines.append(f"## {role_label}  ·  {r['created_at'].isoformat()}")
        lines.append("")
        lines.append(r["content"])
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


@app.post("/api/sessions/{session_id}/archive")
async def archive_session(session_id: int) -> dict:
    """현재 대화 markdown 으로 변환 후 `/archive/mocha/sessions/<date>/` 에 저장."""
    if not db_pool:
        raise HTTPException(status_code=503, detail="db unavailable")
    async with db_pool.acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT id, title, created_at FROM sessions WHERE id=$1", session_id
        )
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM messages WHERE session_id=$1 ORDER BY id ASC",
            session_id,
        )
    if not rows:
        raise HTTPException(status_code=400, detail="empty session — 대화 없음")
    body = _session_to_markdown(sess, rows)

    import re as _re
    from datetime import date as _date
    safe_title = _re.sub(r"[^\w가-힣\-]+", "_", sess["title"])[:60] or "session"
    date_dir = _ARCHIVE_ROOT / _date.today().isoformat()
    try:
        date_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise HTTPException(status_code=500, detail=f"archive write 권한 없음: {exc}") from exc
    out_path = date_dir / f"{session_id:05d}_{safe_title}.md"
    try:
        out_path.write_text(body, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"archive write 실패: {exc}") from exc
    log.info("[archive] session %d saved → %s (%d bytes)", session_id, out_path, len(body))
    return {
        "ok": True,
        "path": str(out_path),
        "size_bytes": len(body.encode("utf-8")),
        "messages": len(rows),
    }


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: int, format: str = "md") -> StreamingResponse:
    """Download session as markdown. ?format=md (only md supported for now)."""
    if format != "md":
        raise HTTPException(status_code=400, detail="only format=md supported")
    if not db_pool:
        raise HTTPException(status_code=503, detail="db unavailable")
    async with db_pool.acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT id, title, created_at FROM sessions WHERE id=$1", session_id
        )
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        rows = await conn.fetch(
            "SELECT role, content, created_at FROM messages WHERE session_id=$1 ORDER BY id ASC",
            session_id,
        )
    body = _session_to_markdown(sess, rows).encode("utf-8")
    fname = f"mocha-session-{session_id}.md"
    return StreamingResponse(
        iter([body]),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False, log_level="info")
