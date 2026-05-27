"""MOCHA — 자연어로 묻는 Watcha 데이터 분석 AI."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg
import httpx
from claude_agent_sdk import ClaudeAgentOptions, query
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import kpi as kpi_mod

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("mocha")

BASE_DIR = Path(__file__).parent
PLUGIN_DIR = BASE_DIR / "plugins" / "eda"
STATIC_DIR = BASE_DIR / "static"
MIGRATION_FILE = BASE_DIR / "migrations" / "001_init.sql"

PORT = int(os.environ.get("PORT", os.environ.get("DEV_PORT", 8080)))
DATABASE_URL = os.environ["DATABASE_URL"]
MODEL = os.environ.get("MOCHA_MODEL", "claude-sonnet-4-6")

# OAuth: claude.ai team subscription 의 access token 으로 Anthropic API 직접 호출.
# API key (sk-ant-api03-...) 와 다른 인증 — subscription quota 만 소모, 추가 과금 X.
# subprocess CLI spawn overhead (~5-10s) 우회 → fast track 응답 5-8s 가능.
_OAUTH_CRED_PATH = Path(os.environ.get("CLAUDE_OAUTH_CRED", "/root/.claude/.credentials.json"))


def _load_oauth_token() -> str | None:
    """Return current access token or None if missing/expired."""
    try:
        with open(_OAUTH_CRED_PATH) as f:
            d = json.load(f)
        oauth = d.get("claudeAiOauth", {})
        token = oauth.get("accessToken")
        expires_at = oauth.get("expiresAt", 0) / 1000.0  # ms → s
        if not token or time.time() >= expires_at:
            return None
        return token
    except Exception:
        log.exception("OAuth token load failed")
        return None


async def stream_oauth_completion(
    model: str, system: str, user_msg: str, max_tokens: int = 2048,
    history: list[dict] | None = None,
) -> AsyncIterator[tuple[str, str]]:
    """Stream Anthropic Messages via OAuth Bearer (team subscription quota).

    Yields ('text', delta) chunks and a final ('done', cost_json).
    Falls back gracefully on auth/network errors via ('error', detail).
    history: prior [{"role":"user"|"assistant","content":"..."}] messages for context.
    """
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
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "system": system,
        "messages": [*(history or []), {"role": "user", "content": user_msg}],
    }
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST", "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload,
            ) as r:
                if r.status_code != 200:
                    body = await r.aread()
                    yield ("error", f"HTTP {r.status_code}: {body.decode()[:300]}")
                    return
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
    except Exception as e:
        log.exception("OAuth streaming failed")
        yield ("error", f"streaming error: {e}")

# 세션당 USD 캡 — 풀 EDA 1회 실측 ~$1.6, 2배 헤드룸으로 $3.
# 폭주(무한 루프 등) 가드. 초과 시 ResultMessage(subtype="error_max_budget_usd").
MAX_BUDGET_USD = float(os.environ.get("MOCHA_MAX_BUDGET_USD", "3.0"))
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


async def _hydrate_kpi_cache_from_db():
    """서버 startup 시 호출: DB 의 KPI summary/series 캐시를 in-memory 로 로드.

    Staleness: 같은 KST date 안에 만들어진 row 만 fresh (사용자 명시 — 데이터는
    하루 1회 갱신).  Stale row 는 hydrate skip → 다음 prewarm 이 재계산."""
    from datetime import datetime, timezone, timedelta
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
    log.info(f"[hydrate] loaded {n} cache rows from DB (today KST)")
    return n


async def _persist_kpi_cache(domain, start_d, end_d, cts_str, summary, series):
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


# Lazy filter prewarm — domain×start×end 단위로 한 번만 실행
_LAZY_PREWARMED: set = set()
_LAZY_PREWARM_SEM = None  # initialized in lifespan


async def _lazy_prewarm_filters(domain: str, start_d, end_d) -> None:
    """도메인 단일 content_type / action_type 필터 조합을 background 로 캐시.

    사용자가 default 진입 후 1-2분 안에 단일 필터 클릭 시 즉시 응답."""
    import asyncio
    key = (domain, start_d, end_d)
    if key in _LAZY_PREWARMED:
        return
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


async def _long_prewarm_subprocess():
    """30-day fast-inline KPI prewarm — each domain in its own subprocess.

    main asyncio loop stays responsive (no GIL). After child exits, read
    the persisted row from DB and hot-load into in-memory cache so the
    very next user query hits instantly.
    """
    import asyncio
    from datetime import date as _date, timedelta
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


async def prewarm_dashboards():
    """Startup background task — DB hit 면 skip, miss 면 계산 + DB upsert.

    데이터가 하루 1회 갱신되니까 같은 KST date 안에 이미 계산된 row 가 있으면
    재계산 안 함.  서버 재시작 후에도 즉시 응답."""
    import asyncio
    from datetime import date as _date, timedelta
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
    asyncio.create_task(_long_prewarm_subprocess())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    import asyncio
    log.info("Connecting to PostgreSQL")
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with db_pool.acquire() as conn:
        await conn.execute(MIGRATION_FILE.read_text())
    log.info(
        "Migrations applied. Listening on :%d (model=%s, max_budget=$%.2f)",
        PORT, MODEL, MAX_BUDGET_USD,
    )

    # Hydrate in-memory KPI cache from DB (skip if today's row already exists)
    try:
        await _hydrate_kpi_cache_from_db()
    except Exception:
        log.exception("[hydrate] failed (continuing anyway)")

    # Background prewarm — DB cache hit if today's row present, else compute
    prewarm_task = asyncio.create_task(prewarm_dashboards())

    yield

    log.info("Shutting down")
    prewarm_task.cancel()
    await db_pool.close()


app = FastAPI(lifespan=lifespan, title="MOCHA")


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    """Force browsers to re-fetch static assets on every load — avoids
    the 'site looks unchanged after restart' issue from stale JS/CSS."""
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug")
async def debug_page():
    """Browser-side debug page — no JS, no CSS, just raw status of mocha.

    DevTools 없이도 사이트가 정상인지 확인 가능. 모든 KPI / insights
    endpoint 직접 호출 + 결과 표시."""
    import urllib.parse
    from datetime import date as _date, timedelta
    rows = ["<h1>🔍 MOCHA Debug</h1><pre>"]
    rows.append(f"server time: {int(time.time())}s")
    rows.append(f"db_pool: {'OK' if db_pool else 'NONE'}")
    rows.append("")
    rows.append("=== 도메인별 KPI / Insight cache 상태 ===")
    for domain in ("galaxy", "mars", "adult"):
        try:
            rng = kpi_mod.available_range(domain)
            end_d = _date.fromisoformat(rng["max"])
            start_d = end_d - timedelta(days=6)
            sum_key = ("summary", domain, start_d.isoformat(), end_d.isoformat(), tuple(), tuple())
            in_mem = "HIT" if kpi_mod._cache_get(sum_key) else "MISS"
            rows.append(f"  {domain:8s} default {start_d}~{end_d}  in-memory: {in_mem}")
        except Exception as e:
            rows.append(f"  {domain:8s} ERR: {e}")
    rows.append("")
    rows.append("=== Endpoints — click to test ===")
    for d in ("galaxy", "mars", "adult"):
        rng = kpi_mod.available_range(d)
        end_d = _date.fromisoformat(rng["max"])
        start_d = end_d - timedelta(days=6)
        qs = f"start={start_d}&end={end_d}"
        rows.append(f'  <a href="/api/kpi/{d}/summary?{qs}">summary {d}</a>')
        rows.append(f'  <a href="/api/kpi/{d}/insights?{qs}">insights {d}</a>')
    rows.append("</pre>")
    return StreamingResponse(iter(["\n".join(rows)]), media_type="text/html")


# Per-request cache buster — browser 가 옛 JS 강제로 새로 받게.
def _asset_v() -> str:
    return str(int(time.time()))


@app.get("/")
async def root() -> StreamingResponse:
    """Inject startup timestamp into static asset URLs so the browser
    fetches fresh JS/CSS on every server restart (cache buster)."""
    html = (STATIC_DIR / "index.html").read_text()
    html = html.replace("/static/style.css", f"/static/style.css?v={_asset_v()}")
    html = html.replace("/static/notion.css", f"/static/notion.css?v={_asset_v()}")
    html = html.replace("/static/dashboard.js", f"/static/dashboard.js?v={_asset_v()}")
    html = html.replace("/static/app.js", f"/static/app.js?v={_asset_v()}")
    # mascot images now loaded via CSS background-image — no HTML rewrite needed.
    # (kept as no-op for safety if old <img> tags reappear)
    html = html.replace("/static/mascot.png\"", f"/static/mascot.png?v={_asset_v()}\"")
    html = html.replace("/static/mascot-icon.png\"", f"/static/mascot-icon.png?v={_asset_v()}\"")
    return StreamingResponse(
        iter([html]),
        media_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# EDA artifacts (figures, reports) live under /tmp/eda/<session>/. Serve them
# so the chat UI can inline-render charts produced by the eda-figures skill.
EDA_DIR = Path("/tmp/eda")
EDA_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/eda-files", StaticFiles(directory=EDA_DIR), name="eda-files")


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
    result = kpi_mod.summary(domain, start_d, end_d, content_types=cts, action_types=ats)
    # Background: 같은 (domain, start, end) 의 단일 필터 조합을 미리 채워둠.
    # 사용자가 다음 체크박스 클릭 시 즉시 hit.
    import asyncio as _asyncio
    _asyncio.create_task(_lazy_prewarm_filters(domain, start_d, end_d))
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
        return kpi_mod.series_response(
            domain, start_d, end_d,
            content_types=cts, action_types=ats, label=label,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown KPI label: {label}")


# ── AI insights ─────────────────────────────────────────────────

INSIGHT_SYSTEM_PROMPT = """Watcha data analyst. KO output. JSON only.

Pick 3-5 angles from: trend (delta%), spike, KPI relation, biz meaning.
Each bullet = **one short Korean sentence** (≤80 chars). **bold** key numbers.
No fabricated facts. No prose/code fences.

Format: {"bullets":["...","...","..."]}
"""


INSIGHT_MODEL = os.environ.get("MOCHA_INSIGHT_MODEL", "claude-haiku-4-5-20251001")


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
    summary = kpi_mod.summary(domain, start_d, end_d, content_types=cts)
    series = kpi_mod.series_response(domain, start_d, end_d, content_types=cts)
    prompt = _build_insight_prompt(summary, series)

    options = ClaudeAgentOptions(
        model=INSIGHT_MODEL,
        system_prompt=INSIGHT_SYSTEM_PROMPT,
        max_turns=1,
        permission_mode="bypassPermissions",
    )
    chunks: list[str] = []
    try:
        async for msg in query(prompt=prompt, options=options):
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
    return {"bullets": [str(b) for b in bullets[:8]]}


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


GATEWAY_SYSTEM_PROMPT = """JSON only. `{...}`. No prose/fences.

Schema:
{"track":"fast|slow","intent":"narrow_top_n|narrow_distribution|narrow_count|interpretive_qa|broad_eda|ab_test|report|notion|small_talk","domain":"ml_1m|watcha_main|adult|pedia|unknown","summary":"<KO 1-line>"}

Intent:
- narrow_count: 1 scalar (얼마/몇/평균/총합/DAU/CVR).
- narrow_top_n: rank/list (TOP/탑/인기/큰손).
- narrow_distribution: dist/trend (분포/추이/일별/시간대).
- interpretive_qa: why/how/diff (왜/이유/차이).
- broad_eda: multi-metric overview.
- ab_test, report, notion, small_talk: as named.

Track: narrow_*/interpretive_qa/notion/small_talk→fast. broad_eda/ab_test/report→slow. ambiguous→slow.

Domain: ml-1m/movielens→ml_1m. 왓챠/mars/시청/rental/구매/graph_modeling/next_watch/user_bert→watcha_main. 성인/adult/NSFW/rec_adult→adult. 피디아/갤럭시/galaxy/별점/보싶→pedia. else→unknown.
"""


GATEWAY_MODEL = os.environ.get("MOCHA_GATEWAY_MODEL", "claude-haiku-4-5-20251001")
# OAuth direct + Haiku — subprocess CLI 우회로 turn 낭비 X, Sonnet 5h rate-limit 회피.
FAST_LEAD_MODEL = os.environ.get("MOCHA_FAST_LEAD_MODEL", "claude-haiku-4-5-20251001")

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
                 "interpretive_qa", "notion", "small_talk"}


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
    track = "fast" if intent in _FAST_INTENTS else "slow"
    result = {"track": track, "intent": intent, "domain": domain,
              "summary": question.strip()[:80]}
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
        system_prompt=GATEWAY_SYSTEM_PROMPT,
        max_turns=1,
        permission_mode="bypassPermissions",
    )
    chunks: list[str] = []
    try:
        async for msg in query(prompt=question, options=options):
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


async def _stream_response(session_id: int, message: str) -> AsyncIterator[str]:
    async with db_pool.acquire() as conn:
        sess = await conn.fetchrow(
            "SELECT id, sdk_session_id FROM sessions WHERE id=$1",
            session_id,
        )
        if not sess:
            yield _sse("error", {"error": "session not found"})
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
    track_hint = (
        f"\n## Gateway: track={classification['track']} "
        f"intent={classification['intent']} q={classification.get('summary', '')}\n"
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
    # KPI summary 동기 fetch 시간이 기간에 비례.
    # 30일 cap — galaxy 30일 ~30-40s (cold), prewarm 후 즉시. 90일 prewarm 은 5분+ 비용 큼.
    # 더 긴 기간은 시스템 프롬프트에 "대시보드/BigQuery 권장" 안내.
    FAST_INLINE_MAX_DAYS = 30
    if is_fast and domain in ("galaxy", "mars", "adult"):
        try:
            from datetime import date as _date, timedelta
            rng = kpi_mod.available_range(domain)
            end_d = _date.fromisoformat(rng["max"])
            requested_days = max(1, int(classification.get("period_days", 7)))
            actual_days = min(requested_days, FAST_INLINE_MAX_DAYS)
            min_d = _date.fromisoformat(rng["min"])
            start_d = max(end_d - timedelta(days=actual_days - 1), min_d)
            t_fetch = time.time()
            import asyncio as _asyncio
            kpi_full = await _asyncio.to_thread(kpi_mod.summary, domain, start_d, end_d, None, None)
            log.info(f"[fast-inline] {domain} {start_d}~{end_d} ({actual_days}d) fetched in {time.time()-t_fetch:.1f}s")
            # 큰 시계열 / 메타 필드 제거 (top-N + 핵심 KPI + files_read 만 남김)
            DROP = {"timeseries", "hourly_activity", "pareto_curve",
                    "rating_distribution", "available_content_types",
                    "available_action_types", "supports",
                    "content_types", "action_types"}
            trimmed = {k: v for k, v in kpi_full.items() if k not in DROP}
            fast_kpi_inline = {
                "period": f"{start_d} ~ {end_d}",
                "source_path": {
                    "galaxy": "/archive/rec_galaxy/behavior_logs/",
                    "mars":   "/archive/user_bert/behavior_logs2/train/",
                    "adult":  "/archive/rec_adult/behavior_logs/",
                }.get(domain, "—"),
                "period_days": actual_days,
                "requested_days": requested_days,
                "capped": requested_days > actual_days,
                "data": trimmed,
            }
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
        # KPI JSON minified — saves ~20-30% input tokens.
        kpi_json = json.dumps(fast_kpi_inline['data'], ensure_ascii=False, separators=(",", ":"))
        files_str = ", ".join(fast_kpi_inline['data'].get('files_read', []) or [])
        fast_system = (
            f"Watcha analyst. KO answer only. Use KPI below.\n"
            f"{domain.upper()} {fast_kpi_inline['period']} ({fast_kpi_inline['period_days']}d) "
            f"intent={classification['intent']} q={classification.get('summary', '')}\n"
            f"source={fast_kpi_inline['source_path']} files={fast_kpi_inline['data'].get('files_read', [])}\n"
            f"{cap_note}"
            f"KPI:{kpi_json}\n\n"
            f"## Output format — Toss PANDA style (MUST follow this exact structure):\n\n"
            f"# [질문 한 줄 요약]\n\n"
            f"## 📅 결과\n"
            f"[마크다운 표 — 핵심 숫자, ≤10행]\n\n"
            f"## 📊 집계 기준\n"
            f"- 기간: {fast_kpi_inline['period']} ({fast_kpi_inline['period_days']}일)\n"
            f"- 도메인: {domain.upper()}\n"
            f"- 기준: [정의 — 어떤 action/필터/계산식 — 한 줄]\n"
            f"- 해석: [용어 의미 — 한 줄]\n\n"
            f"## 📂 데이터 소스\n"
            f"- 경로: `{fast_kpi_inline['source_path']}`\n"
            f"- 파일: `{files_str}`\n\n"
            f"## 💡 주요 인사이트\n"
            f"✅ **[항목 1 한 줄 결론 — bold]**\n"
            f"   - [부연/숫자]\n"
            f"   - [해석/비교 — 다른 KPI 또는 평균과 비교]\n\n"
            f"✅ **[항목 2 한 줄 결론]**\n"
            f"   - [부연]\n"
            f"   - [해석]\n\n"
            f"(필요시 ✅ 3번째)\n\n"
            f"Rules: KO only. 숫자엔 비교 맥락 곁들임 (예: '평균 대비 +X%'). "
            f"부연 = 숫자/사실. 해석 = '~로 보임/시사함'. "
            f"No tools/thinking/explore text. No extra sections outside the 4 blocks above.\n"
        )
        # Fetch prior messages for conversation context (last 3 exchanges before this turn)
        fast_history: list[dict] = []
        try:
            async with db_pool.acquire() as conn:
                prev_msgs = await conn.fetch(
                    "SELECT role, content FROM messages "
                    "WHERE session_id=$1 "
                    "AND id < (SELECT max(id) FROM messages WHERE session_id=$1) "
                    "ORDER BY id DESC LIMIT 6",
                    session_id,
                )
            fast_history = [{"role": r["role"], "content": r["content"]} for r in reversed(prev_msgs)]
        except Exception:
            log.exception("Failed to fetch fast-track conversation history")

        full_text = []
        usage_info = None
        async for kind, payload_ in stream_oauth_completion(
            model=lead_model, system=fast_system, user_msg=message, max_tokens=2048,
            history=fast_history or None,
        ):
            if kind == "text":
                full_text.append(payload_)
                yield _sse("text", {"text": payload_})
            elif kind == "done":
                try:
                    usage_info = json.loads(payload_)
                except json.JSONDecodeError:
                    usage_info = None
            elif kind == "error":
                yield _sse("error", {"error": payload_})
                errored = True if "errored" in dir() else True
                break
        # 통합 답변 DB persist
        if full_text:
            assistant_text = "".join(full_text)
            async with db_pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO messages(session_id, role, content) VALUES($1, 'assistant', $2)",
                    session_id, assistant_text,
                )
        # cost = 0 (subscription quota — API 호출 X)
        yield _sse("done", {"cost_usd": 0.0, "via": "oauth_direct", "usage": usage_info})
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

    try:
        async for msg in query(prompt=message, options=options):
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
                    yield _sse("error", {
                        "error": f"분석이 비정상 종료됨 — {reason}",
                        "subtype": subtype,
                        "is_error": is_error,
                        "cost_usd": cost,
                    })
                else:
                    yield _sse("done", {"cost_usd": cost})
                break

            elif cls == "RateLimitEvent":
                yield _sse("rate_limit", {"message": str(msg)})

    except Exception as exc:
        log.exception("Agent query failed")
        errored = True
        yield _sse("error", {"error": str(exc)})

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


@app.post("/api/sessions/{session_id}/chat")
async def chat(session_id: int, req: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_response(session_id, req.message),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False, log_level="info")
