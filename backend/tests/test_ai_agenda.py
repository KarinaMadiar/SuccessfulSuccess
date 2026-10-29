"""Tests for the AI agenda parser, Lambda handler, and ai_suggestion persistence."""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.agenda import (
    PROMPT_VERSION,
    AgendaParseError,
    ParsedAgenda,
    cost_usd,
    parse_agenda,
)
from app.ai.agenda_lambda import MAX_TEXT_LENGTH, handler
from tests.tokens import make_token, make_verifier


@pytest.fixture
def local_private_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def local_verifier(local_private_key):
    return make_verifier(local_private_key)


def _mock_tool_message(
    tool_input: dict | None,
    input_tokens: int = 310,
    output_tokens: int = 120,
    stop_reason: str = "tool_use",
):
    content = []
    if tool_input is not None:
        content.append(
            SimpleNamespace(
                type="tool_use",
                id="toolu_01test",
                name="record_agenda",
                input=tool_input,
            )
        )
    else:
        content.append(SimpleNamespace(type="text", text="I cannot parse this."))
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def test_cost_usd_calculation():
    usage = {"input_tokens": 1_000, "output_tokens": 500}
    # Opus 5.5: 1000 * $4/M + 500 * $20/M = 0.004 + 0.010 = 0.014
    assert cost_usd("anthropic.claude-opus-5-5", usage) == 0.014
    # Haiku 5.5: 1000 * $0.10/M + 500 * $0.50/M = 0.0001 + 0.00025 = 0.00035
    assert cost_usd("anthropic.claude-haiku-5-5", usage) == 0.00035


@patch("app.ai.agenda.client")
def test_parse_agenda_success(mock_client):
    mock_client.messages.create.return_value = _mock_tool_message(
        {
            "title": "Синк по прайсингу",
            "starts_at": "2026-11-02T10:00:00+02:00",
            "duration_minutes": 45,
            "items": [
                {"topic": "нові тарифи Pro", "owner": "Олена", "minutes": 15},
                {"topic": "фідбек від клієнтів", "owner": "Taras", "minutes": None},
                {"topic": "що робимо з річною знижкою", "owner": None, "minutes": None},
            ],
            "action_items": [
                {
                    "task": "збирає порівняння з конкурентами",
                    "owner": "Taras",
                    "due": "2026-11-06",
                }
            ],
            "language": "uk",
        },
        input_tokens=420,
        output_tokens=165,
    )

    agenda, usage = parse_agenda(
        "Пн 10:00, синк по прайсингу, 45 хв. 1) нові тарифи Pro — Олена, 15 хв "
        "2) фідбек від клієнтів — Taras 3) що робимо з річною знижкою. "
        "Taras до п'ятниці збирає порівняння з конкурентами.",
        today=date(2026, 10, 29),
        tz="Europe/Kyiv",
    )

    assert isinstance(agenda, ParsedAgenda)
    assert agenda.title == "Синк по прайсингу"
    assert agenda.duration_minutes == 45
    assert len(agenda.items) == 3
    assert agenda.items[0].owner == "Олена"
    assert agenda.items[0].minutes == 15
    assert len(agenda.action_items) == 1
    assert agenda.action_items[0].due == date(2026, 11, 6)
    assert agenda.language == "uk"
    assert usage == {"input_tokens": 420, "output_tokens": 165}


@patch("app.ai.agenda.client")
def test_parse_agenda_retries_once_on_validation_error(mock_client):
    # First attempt has invalid minutes (-5), second attempt is valid
    invalid_msg = _mock_tool_message(
        {
            "title": "Sync",
            "items": [{"topic": "Pricing", "minutes": -5}],
            "language": "en",
        },
        input_tokens=300,
        output_tokens=100,
    )
    valid_msg = _mock_tool_message(
        {
            "title": "Sync",
            "items": [{"topic": "Pricing", "minutes": 15}],
            "language": "en",
        },
        input_tokens=400,
        output_tokens=90,
    )
    mock_client.messages.create.side_effect = [invalid_msg, valid_msg]

    agenda, usage = parse_agenda("Sync: Pricing 15m", today=date(2026, 10, 29), tz="UTC")
    assert agenda.items[0].minutes == 15
    assert usage == {"input_tokens": 700, "output_tokens": 190}
    assert mock_client.messages.create.call_count == 2


@patch("app.ai.agenda.client")
def test_parse_agenda_raises_when_no_tool_use(mock_client):
    mock_client.messages.create.return_value = _mock_tool_message(None, stop_reason="refusal")
    with pytest.raises(AgendaParseError, match="no agenda returned"):
        parse_agenda("Milk, eggs, bread", today=date(2026, 10, 29), tz="UTC")


def test_lambda_handler_rejects_unauthenticated():
    res = handler({"headers": {}, "body": json.dumps({"text": "Hello"})})
    assert res["statusCode"] == 401


def test_lambda_handler_rejects_oversized_text(local_verifier, local_private_key, monkeypatch):
    monkeypatch.setattr("app.ai.agenda_lambda.get_verifier", lambda: local_verifier)
    token = make_token(local_private_key, sub="user-123")
    res = handler(
        {
            "headers": {"Authorization": f"Bearer {token}"},
            "body": json.dumps(
                {
                    "text": "x" * (MAX_TEXT_LENGTH + 1),
                    "today": "2026-10-29",
                    "tz": "Europe/Kyiv",
                }
            ),
        }
    )
    assert res["statusCode"] == 413


@patch("app.ai.agenda_lambda.parse_agenda")
def test_lambda_handler_success_and_logs(
    mock_parse, local_verifier, local_private_key, monkeypatch, caplog
):
    monkeypatch.setattr("app.ai.agenda_lambda.get_verifier", lambda: local_verifier)
    token = make_token(local_private_key, sub="user-123")
    sample_agenda = ParsedAgenda(
        title="Pricing Sync",
        starts_at="2026-11-02T10:00:00+02:00",
        duration_minutes=45,
        items=[{"topic": "Pro tier", "owner": "Olena", "minutes": 15}],
        action_items=[],
        language="en",
    )
    mock_parse.return_value = (
        sample_agenda,
        {"input_tokens": 412, "output_tokens": 148},
    )

    with caplog.at_level("INFO", logger="meetings.ai"):
        res = handler(
            {
                "headers": {"authorization": f"Bearer {token}"},
                "body": json.dumps(
                    {
                        "text": "Mon 10:00 Pricing Sync 45m. 1) Pro tier - Olena 15m",
                        "today": "2026-10-29",
                        "tz": "Europe/Kyiv",
                    }
                ),
            }
        )

    assert res["statusCode"] == 200
    payload = json.loads(res["body"])
    assert payload["agenda"]["title"] == "Pricing Sync"
    assert payload["prompt_version"] == PROMPT_VERSION

    # Verify structured CloudWatch log line
    log_lines = [r.message for r in caplog.records if "agenda_parsed" in r.message]
    assert len(log_lines) == 1
    logged = json.loads(log_lines[0])
    assert logged["event"] == "agenda_parsed"
    assert logged["user"] == "user-123"
    assert logged["prompt_version"] == PROMPT_VERSION
    assert logged["input_tokens"] == 412
    assert logged["output_tokens"] == 148
    assert "latency_ms" in logged
    assert "cost_usd" in logged


async def test_save_meeting_persists_ai_suggestion(client, meeting_payload):
    suggestion = {
        "agenda": {
            "title": "Sprint planning",
            "starts_at": "2026-09-10T10:00:00+03:00",
            "duration_minutes": 60,
            "items": [{"topic": "Backlog grooming", "owner": "Ostap", "minutes": 30}],
            "action_items": [],
            "language": "en",
        },
        "model": "anthropic.claude-opus-5-5",
        "prompt_version": "agenda-v1",
    }
    payload_with_ai = {**meeting_payload, "ai_suggestion": suggestion}

    response = await client.post("/api/v1/meetings", json=payload_with_ai)
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["ai_suggestion"] == suggestion

    fetched = (await client.get(f"/api/v1/meetings/{created['id']}")).json()
    assert fetched["ai_suggestion"] == suggestion
