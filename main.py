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

SYSTEM_PROMPT = """\
당신은 MOCHA — Watcha 사내 데이터 분석 AI 어시스턴트입니다.

사용자가 자연어로 데이터 질문을 하면 eda 플러그인의 skill을 사용해 답변합니다.

## 라우팅 규칙
- 데이터 분석/EDA 요청 → `Skill(eda)` 호출. 자연어 질문을 인자로 넘김
- "노션에 올려줘" → `Skill(notion-publish)`
- 일반 대화 → 직접 답변 (단, 데이터 관련이면 eda로 위임)

## 답변 원칙
- 한국어, 친근하면서 정확하게
- KST 시간대 보정 필수
- PANDA 스타일: 결과(표) + 집계 기준 + 인사이트 3-5개
- 사용자가 묻지 않은 곁가지 정보 절대 X
- ML 용어는 풀어쓰기
- 사과/한계는 마지막 한 줄

세부 EDA 동작은 `/eda` skill의 SKILL.md를 따릅니다.
"""

db_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    log.info("Connecting to PostgreSQL")
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with db_pool.acquire() as conn:
        await conn.execute(MIGRATION_FILE.read_text())
    log.info("Migrations applied. Listening on :%d", PORT)

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
        permission_mode="bypassPermissions",
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        max_turns=20,
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
