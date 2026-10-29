"""Local/dev fallback endpoint for AI agenda parsing.

In production on AWS, the browser calls the standalone agenda-parser Lambda's
Function URL (infra/ai.yml) directly outside the VPC. In local Docker Compose
development (when NEXT_PUBLIC_PARSER_URL is empty), this endpoint lets the UI
exercise the exact same parser logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.ai.agenda import PROMPT_VERSION, AgendaParseError, cost_usd, parse_agenda
from app.ai.agenda_lambda import MAX_TEXT_LENGTH
from app.auth import CurrentUserDep
from app.config import settings

router = APIRouter(prefix="/ai", tags=["ai"])
log = logging.getLogger("meetings.ai")


class ParseAgendaRequest(BaseModel):
    text: str
    today: str | None = None
    tz: str | None = None


@router.post("/parse-agenda", summary="Parse free-form text into a structured agenda")
async def parse_agenda_endpoint(
    payload: ParseAgendaRequest,
    user: CurrentUserDep,
) -> Any:
    if not payload.text or not payload.text.strip():
        return JSONResponse(status_code=422, content={"error": "Text is required."})

    if len(payload.text) > MAX_TEXT_LENGTH:
        return JSONResponse(
            status_code=413,
            content={"error": f"Text exceeds the maximum length of {MAX_TEXT_LENGTH} characters."},
        )

    try:
        today_val = date.fromisoformat(payload.today) if payload.today else date.today()
    except ValueError:
        return JSONResponse(status_code=422, content={"error": "Invalid 'today' ISO date."})

    tz_val = payload.tz or settings.app_timezone
    started = time.monotonic()

    try:
        agenda, usage = await asyncio.to_thread(parse_agenda, payload.text, today_val, tz_val)
    except AgendaParseError as exc:
        return JSONResponse(status_code=422, content={"error": str(exc)})
    except Exception as exc:
        err_name = type(exc).__name__
        if "RateLimit" in err_name or "Throttling" in err_name or "429" in str(exc):
            return JSONResponse(
                status_code=429,
                content={
                    "error": "The AI service is currently busy (throttled). Please try again."
                },
            )
        log.exception("Unexpected error calling Bedrock")
        return JSONResponse(
            status_code=503,
            content={"error": "AI agenda parser is temporarily unavailable."},
        )

    latency_ms = int((time.monotonic() - started) * 1000)
    log.info(
        json.dumps(
            {
                "event": "agenda_parsed",
                "user": user.sub,
                "model": settings.PARSER_MODEL,
                "prompt_version": PROMPT_VERSION,
                **usage,
                "latency_ms": latency_ms,
                "cost_usd": cost_usd(settings.PARSER_MODEL, usage),
            }
        )
    )

    return {
        "agenda": agenda.model_dump(mode="json"),
        "model": settings.PARSER_MODEL,
        "prompt_version": PROMPT_VERSION,
    }
