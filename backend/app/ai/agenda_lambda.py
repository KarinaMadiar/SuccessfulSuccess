"""AWS Lambda handler for the standalone agenda-parser function URL.

Runs outside the VPC to reach Amazon Bedrock directly over HTTPS without a NAT
gateway or VPC interface endpoint. Validates the caller's Cognito access token,
enforces the 10,000-character limit, calls parse_agenda, and logs token usage,
latency, and cost on a single structured JSON line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date
from typing import Any

from app.ai.agenda import (
    PROMPT_VERSION,
    AgendaParseError,
    cost_usd,
    parse_agenda,
)
from app.auth import AuthError, AuthNotConfiguredError, CurrentUser, get_verifier
from app.config import settings

log = logging.getLogger("meetings.ai")
log.setLevel(logging.INFO)

MAX_TEXT_LENGTH = 10_000


def verify_cognito_token(auth_header: str) -> CurrentUser:
    """Verify a Bearer Cognito access token synchronously for the Lambda handler."""
    if not auth_header:
        raise AuthError("Sign in to continue.")
    parts = auth_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise AuthError("Sign in to continue.")
    token = parts[1].strip()
    verifier = get_verifier()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(verifier.verify(token))).result()
    return asyncio.run(verifier.verify(token))


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda Function URL entry point for POST agenda parsing requests."""
    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    try:
        user = verify_cognito_token(headers.get("authorization", ""))
    except (AuthError, AuthNotConfiguredError) as exc:
        return _json_response(401, {"error": str(exc) or "Unauthorized"})

    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8", errors="replace")

    try:
        body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
    except json.JSONDecodeError:
        return _json_response(400, {"error": "Invalid JSON body."})

    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        return _json_response(422, {"error": "Text is required."})

    if len(text) > MAX_TEXT_LENGTH:
        return _json_response(
            413,
            {"error": f"Text exceeds the maximum length of {MAX_TEXT_LENGTH} characters."},
        )

    try:
        today_val = date.fromisoformat(body["today"]) if body.get("today") else date.today()
    except (ValueError, TypeError):
        return _json_response(422, {"error": "Invalid 'today' ISO date."})

    tz_val = str(body.get("tz") or settings.app_timezone)

    started = time.monotonic()
    try:
        agenda, usage = parse_agenda(text, today_val, tz_val)
    except AgendaParseError as e:
        return _json_response(422, {"error": str(e)})
    except Exception as e:
        err_name = type(e).__name__
        if "RateLimit" in err_name or "Throttling" in err_name or "429" in str(e):
            return _json_response(
                429, {"error": "The AI service is currently busy (throttled). Please try again."}
            )
        log.exception("Unexpected error calling Bedrock")
        return _json_response(503, {"error": "AI agenda parser is temporarily unavailable."})

    latency_ms = int((time.monotonic() - started) * 1000)
    log_entry = {
        "event": "agenda_parsed",
        "user": user.sub,
        "model": settings.PARSER_MODEL,
        "prompt_version": PROMPT_VERSION,
        **usage,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd(settings.PARSER_MODEL, usage),
    }
    log.info(json.dumps(log_entry))

    return _json_response(
        200,
        {
            "agenda": agenda.model_dump(mode="json"),
            "model": settings.PARSER_MODEL,
            "prompt_version": PROMPT_VERSION,
        },
    )
