"""Tests for builder and mailer Lambda handlers."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.reports.lambda_handler import handler as builder_handler
from app.reports.lambda_handler import parse_event
from app.reports.mailer import handler as mailer_handler


def test_parse_event_sqs():
    event = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "body": json.dumps({"week": "2026-W39", "source": "sqs"}),
            }
        ]
    }
    payload, trigger = parse_event(event)
    assert trigger == "sqs"
    assert payload["week"] == "2026-W39"


def test_parse_event_schedule_via_sqs():
    event = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "body": json.dumps({"week": None, "source": "schedule"}),
            }
        ]
    }
    payload, trigger = parse_event(event)
    assert trigger == "schedule"
    assert payload["week"] is None


def test_parse_event_direct_schedule():
    event = {"source": "schedule"}
    payload, trigger = parse_event(event)
    assert trigger == "schedule"


@patch("app.reports.lambda_handler.s3_client")
@patch("app.reports.lambda_handler.build_weekly_report")
def test_builder_handler_success(mock_build, mock_s3, monkeypatch):
    monkeypatch.setenv("REPORTS_BUCKET", "test-bucket")
    mock_build.return_value = b"test,csv,data"

    event = {
        "Records": [
            {
                "eventSource": "aws:sqs",
                "body": json.dumps({"week": "2026-W40"}),
            }
        ]
    }
    res = builder_handler(event)
    assert res["status"] == "ok"
    assert res["week"] == "2026-W40"
    assert res["bucket"] == "test-bucket"
    assert res["key"] == "reports/2026-W40.csv"
    mock_s3.put_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="reports/2026-W40.csv",
        Body=b"test,csv,data",
        ContentType="text/csv",
    )


def test_builder_handler_dlq_failure_simulation(monkeypatch):
    monkeypatch.setenv("REPORTS_BUCKET", "test-bucket")
    event = {"week": "FAIL"}
    with pytest.raises(RuntimeError, match="Simulated failure for DLQ test"):
        builder_handler(event)


@patch("app.reports.mailer.ses_client")
@patch("app.reports.mailer.s3_client")
def test_mailer_handler_success(mock_s3, mock_ses, monkeypatch):
    monkeypatch.setenv("SENDER_EMAIL", "reports@successful.pp.ua")
    monkeypatch.setenv("RECIPIENT_EMAILS", "madiar.pn@ucu.edu.ua")

    mock_s3_body = MagicMock()
    mock_s3_body.read.return_value = b"csv,header\n1,2"
    mock_s3.get_object.return_value = {"Body": mock_s3_body}
    mock_ses.send_email.return_value = {"MessageId": "msg-12345"}

    event = {
        "Records": [
            {
                "eventSource": "aws:s3",
                "s3": {
                    "bucket": {"name": "test-bucket"},
                    "object": {"key": "reports/2026-W40.csv"},
                },
            }
        ]
    }
    res = mailer_handler(event)
    assert res["status"] == "sent"
    assert res["message_id"] == "msg-12345"
    assert res["week"] == "2026-W40"
    mock_ses.send_email.assert_called_once()
