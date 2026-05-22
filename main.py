"""MOCHA — 자연어로 묻는 Watcha 데이터 분석 AI."""
from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import asyncpg
from claude_agent_sdk import ClaudeAgentOptions, query
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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

# 세션당 USD 캡 — 풀 EDA 1회 실측 ~$1.6, 2배 헤드룸으로 $3.
# 폭주(무한 루프 등) 가드. 초과 시 ResultMessage(subtype="error_max_budget_usd").
MAX_BUDGET_USD = float(os.environ.get("MOCHA_MAX_BUDGET_USD", "3.0"))
# NOTE: TaskBudget(token pacing hint)은 beta header(task-budgets-2026-03-13) 가 필요해서
# sonnet-4-6 같은 일반 모델에선 API 400. Opus 일부 버전만 지원. 안정성 위해 비활성.
# max_budget_usd 만으로 폭주 가드 충분.

DOMAIN_SPECS = {
    "ml_1m": "**ml_1m** (public 데모): `data/rating_prediction/ml-1m/` (ratings.ftr + movies.parquet). value 1-5 정수, min-20 필터, single-type Movie.",
    "watcha_main": "**watcha_main** (mars 본 서비스): `/archive/graph_modeling/`, `/archive/next_watch/`, `/archive/next_purchase/`, `/archive/user_bert/` (전용) + `/archive/rating_prediction/` (pedia 와 공유). 진입 경로 `/archive/graph_modeling/builtin/` 또는 `/archive/next_watch/default/`. value=별점×2 (1-10 → 0.5-5), play/buy 강신호, KG 메타.",
    "adult": "**adult** (rec_adult 성인+): `/archive/rec_adult/`, `/archive/next_adult/`, `/archive/user_bert_adult/`, `/archive/adult_foundation/`. 진입 경로 `/archive/rec_adult/builtin/`. rental+possession 매출, 헤비유저 1명 매출 5%+ 영향, TOP1 제거 시뮬 필수.",
    "pedia": "**pedia** (rec_galaxy 왓챠피디아): `/archive/rec_galaxy/` (전용) + `/archive/rating_prediction/` (watcha_main 과 공유). 진입 경로 `/archive/rec_galaxy/builtin/`. 평점 1-10, multi-behavior (click/search/rate/wish), multi-content-type, 99.94% sparsity.",
    "unknown": "**unknown** (도메인 미정): archive 접근 X. 사용자에게 1회 묻거나 ml_1m default.",
}


SYSTEM_PROMPT_TEMPLATE = """\
당신은 MOCHA — Watcha 사내 데이터 분석 AI 어시스턴트입니다.

## Iron Rule — 속도 최우선

모든 분석은 **단일 Python 블록 (Bash 1회)** 안에서 처리한다. 통계 여러 개 묻혀도 한 블록에 합쳐서 실행. 중간 ls/find/cat 같은 정찰 Bash 금지.

질문이 BROAD 든 NARROW 든 동일. 분석량이 다르면 한 블록 안의 Python 코드만 더 길어지면 됨.

## 도메인 (Gateway 가 정한 domain — 이 도메인의 archive 만 접근)

{domain_block}

**🚫 도메인 격리 Iron rule**: 위 명시된 archive scope 외 경로 접근 절대 금지. 의심되면 사용자에게 1회 확인.

## Sub-skill (standalone, 필요할 때만)

`Skill(eda-figures)` themed 차트 · `Skill(eda-overview)` 기본 통계 · `Skill(eda-casestudy)` TOP 케이스 · `Skill(eda-report)` Markdown 리포트 · `Skill(eda-intake)` brief 대화 · `Skill(notion-publish)` 노션 업로드.

단순 통계/시각화는 sub-skill 도 거치지 말고 pandas + matplotlib 직접이 더 빠름. sub-skill 은 "themed 차트 일관성" 또는 "표준 리포트 형식" 이 진짜 필요할 때만.

## 답변 템플릿 (`plugins/eda/templates/`)

질문 유형 보고 1개 선택 → `Read` → placeholder 채워 답변:
- `01_light_memo.md` — TOP N · 분포 · 단순 통계 (30-50줄)
- `02_full_eda.md` — EDA · 전반 분석 (150-300줄)
- `03_ab_test.md` — A/B test 사후 (200-400줄)
- `04_analysis_report.md` — 분석 노트 mid-size (100-200줄)

## 답변 원칙

- 한국어. PANDA 형식: 질문 요약 → 표/차트 → 집계 기준 → 💡 **인사이트 1-2개 (단순한 답도 필수)**
- 시각화 `/tmp/eda/*.png` 저장 후 답변에 `![](/eda-files/X.png)` inline. 경로만 알려주는 거 금지.
- 차트 1개당 파일 1개 · 막대그래프 vertical · 한글 폰트 `plt.rcParams['font.family']='NanumGothic'`
- 묻지 않은 곁가지 X. 사과/한계는 마지막 한 줄.
"""


def build_system_prompt(domain: str = "unknown") -> str:
    """Gateway 가 정한 domain 의 spec 만 포함시켜 SYSTEM_PROMPT 생성.

    전체 도메인 표 (~5개 행) → 1개 행만 주입 → input token ~40% 절감.
    Phase 2 부활 시 Domain Expert 의 system_prompt 와 일관된 구조.
    """
    spec = DOMAIN_SPECS.get(domain, DOMAIN_SPECS["unknown"])
    return SYSTEM_PROMPT_TEMPLATE.format(domain_block=spec)

db_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    log.info("Connecting to PostgreSQL")
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with db_pool.acquire() as conn:
        await conn.execute(MIGRATION_FILE.read_text())
    log.info(
        "Migrations applied. Listening on :%d (model=%s, max_budget=$%.2f)",
        PORT, MODEL, MAX_BUDGET_USD,
    )

    yield

    log.info("Shutting down")
    await db_pool.close()


app = FastAPI(lifespan=lifespan, title="MOCHA")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


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


GATEWAY_SYSTEM_PROMPT = """JSON 만 출력. 다른 텍스트 / 코드펜스 모두 금지. 첫 글자 `{` 끝 `}`.

사용자 질문을 다음 형식으로 분류:

{
  "track": "fast" | "slow",
  "intent": "narrow_top_n" | "narrow_distribution" | "narrow_count" | "interpretive_qa" | "broad_eda" | "ab_test" | "report" | "notion" | "small_talk",
  "domain": "ml_1m" | "watcha_main" | "adult" | "pedia" | "unknown",
  "summary": "<질문 의도 한 줄 요약>"
}

## Track 분류 룰
- 단순 통계 (TOP N · 분포 · 평균 · 카운트 · 단순 시각화) → fast / narrow_*
- 큰손 / 장르 / 도메인 해석 단일 질문 → fast / interpretive_qa
- 노션 업로드 → fast / notion
- 일반 인사·잡담 → fast / small_talk
- "전반 EDA", "전체 분석", "데이터 특성" → slow / broad_eda
- A/B test 사후 분석 → slow / ab_test
- "리포트 만들어줘", "마크다운 정리" → slow / report
- 모호하거나 다단계 추론 필요 → slow (안전한 default)

## Domain 분류 룰 (질문의 도메인 키워드로 짐작)
- "ml-1m" / "movielens" / 영문 movie title 위주 → ml_1m (public dataset)
- "왓챠" / "rental" / "구매" / "시청" / "wish" 시청-구매 강조 → watcha_main (mars)
- "성인" / "성인+" / "adult" / "rec_adult" / NSFW → adult
- "피디아" / "rec_galaxy" / "별점" / "search" / multi-content-type → pedia
- 어느 쪽도 명확하지 않으면 → unknown (Lead 가 사용자에게 1회 묻거나 ml_1m 가정)
"""


GATEWAY_MODEL = os.environ.get("MOCHA_GATEWAY_MODEL", "claude-haiku-4-5")


async def gateway_classify(question: str) -> dict[str, Any]:
    """Haiku 1턴으로 빠르게 분류 — track + intent + domain + summary.

    Gateway 는 단순 분류 task — Haiku 도 정확도 충분 (sanity 6/6).
    매 query 시 ~2초 / ~$0.0005. Sonnet 대비 ~5배 빠르고 ~10배 저렴.
    """
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
    yield _sse("gateway", {"status": "classified", **classification})

    # Gateway 결정 domain 만 SYSTEM_PROMPT 에 주입 (다른 도메인 행 제거 → token ~40% 절감)
    domain = classification.get("domain", "unknown")
    system_prompt = build_system_prompt(domain)

    # Track 별 추가 hint (Lead 가 Gateway 의 intent / summary 알게)
    track_hint = (
        f"\n\n## Gateway hint\n"
        f"- track: {classification['track']}\n"
        f"- intent: {classification['intent']}\n"
        f"- 요약: {classification.get('summary', '')}\n"
    )
    # fast 는 단순 통계 (Bash 1-2 + 답변) → 6 turn 충분. slow 는 broad/A/B test → 20 turn.
    track_max_turns = 6 if classification["track"] == "fast" else 20

    options = ClaudeAgentOptions(
        cwd=str(BASE_DIR),
        plugins=[{"type": "local", "path": str(PLUGIN_DIR)}],
        skills="all",
        permission_mode="bypassPermissions",
        model=MODEL,
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
                        yield _sse("tool", {"name": tool_name})

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
