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

from agents import AGENTS

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

SYSTEM_PROMPT = """\
당신은 MOCHA — Watcha 사내 데이터 분석 AI 어시스턴트입니다.

## Skill Catalog — 질문 보고 필요한 skill 만 직접 호출 (eda 오케스트레이터 강제 chain 금지)

| 사용자 질문 | 호출할 skill / 직접 처리 | 예상 시간 |
|---|---|---|
| 단순 통계 (TOP N · 분포 · 평균 · 카운트) | **직접 pandas via Bash 1회** (skill X) | ~15-20초 |
| 시각화 ("차트", "그려줘") | **`Skill(eda-figures)`** — themed matplotlib + 색상 룰 자동 적용 | 30-60초 |
| 데이터 개요 ("어떻게 생겼어", "기본 통계") | **`Skill(eda-overview)`** | 30-60초 |
| TOP 케이스 ("큰손 유저", "TOP 콘텐츠") | **`Skill(eda-casestudy)`** | 30-60초 |
| 리포트 생성 ("리포트 만들어", "Markdown") | **`Skill(eda-report)`** | 30-60초 |
| 전체 분석 ("풀 EDA", "전반적으로 분석", "도메인 깊이") | **`Skill(eda)`** — 오케스트레이터 (multi-agent, 위 skill 들 조합) | 2-3분 |
| Brief 수집 ("분석 시작 전 조건 정리") | **`Skill(eda-intake)`** | 대화형 |
| Notion 업로드 | **`Skill(notion-publish)`** | 즉시 |

**라우팅 원칙**:
- 각 skill 은 standalone 호출 가능. 단순 작업에 `Skill(eda)` 거치지 말 것 (overhead 큼).
- 여러 단계 조합이 진짜로 필요한 broad 분석에만 `Skill(eda)`.
- 단순 통계는 skill 도 거치지 말고 pandas 직접 (가장 빠름).

## 데이터 위치 (NARROW 직접 처리 시)
- ML-1M: `data/rating_prediction/ml-1m/ratings.ftr` (user_id/content/value/content_type/updated_at) + `movies.parquet` (movie_id/content/title/year/genres pipe-delimited)
- 다른 도메인 모호하면 1회 묻기. ls/find 금지.

## 답변 원칙
- 한국어. 친근하면서 정확.
- PANDA 형식: 질문 요약 → 표/차트 → 집계 기준 (데이터·기간·행수)
- 시각화는 답변에 `![](/eda-files/X.png)` inline 박을 것 (경로만 알려주면 사용자가 못 봄)
- 묻지 않은 곁가지 X. 사과/한계는 마지막 한 줄.
"""

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

    options = ClaudeAgentOptions(
        cwd=str(BASE_DIR),
        plugins=[{"type": "local", "path": str(PLUGIN_DIR)}],
        skills="all",
        agents=AGENTS,
        permission_mode="bypassPermissions",
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        max_turns=30,
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
        if new_sdk_session:
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
