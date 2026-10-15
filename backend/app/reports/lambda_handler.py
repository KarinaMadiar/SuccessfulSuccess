"""AWS Lambda entry point for report-builder.

Runs inside the VPC, queries the database, generates the weekly CSV report,
and uploads it to S3 through the S3 Gateway VPC Endpoint.
"""

import json
import logging
import os
from typing import Any

import boto3

from app.reports.weekly import build_weekly_report, get_previous_iso_week, get_report_s3_key

logger = logging.getLogger("reports.builder")
logger.setLevel(logging.INFO)

AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

# boto3 client inside VPC communicates with S3 via Gateway VPCEndpoint
s3_client = boto3.client("s3", region_name=AWS_REGION)


def parse_event(event: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Extract the payload and detect whether the invocation came from SQS, schedule, or direct.

    Supports both direct invocations and SQS EventSourceMapping records.
    """
    if "Records" in event and event["Records"]:
        record = event["Records"][0]
        if record.get("eventSource") == "aws:sqs":
            body_raw = record.get("body", "{}")
            try:
                body = json.loads(body_raw)
            except Exception:
                body = {"raw": body_raw}

            # If schedule targeted SQS with {"source": "schedule"}
            if body.get("source") == "schedule":
                return body, "schedule"
            return body, "sqs"

    if event.get("source") in ("schedule", "aws.scheduler"):
        return event, "schedule"

    return event, event.get("source", "direct")


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda handler for report generation."""
    payload, trigger = parse_event(event)

    # If the event does not specify a week, default to the previous ISO week
    week = payload.get("week")
    if not week:
        week = get_previous_iso_week()

    logger.info(
        f"report-builder triggered: trigger={trigger} week={week}",
        extra={"trigger": trigger, "week": week},
    )

    # Controlled failure simulation for Step 7 DLQ testing
    if str(week).upper() in ("FAIL", "ERROR") or payload.get("fail"):
        logger.error(f"Simulating builder failure for DLQ test: week={week}")
        raise RuntimeError(f"Simulated failure for DLQ test (week={week})")

    # Generate CSV bytes from PostgreSQL database
    csv_bytes = build_weekly_report(week)

    bucket = os.environ.get("REPORTS_BUCKET")
    if not bucket:
        raise ValueError("REPORTS_BUCKET environment variable is not set")

    key = get_report_s3_key(week)

    logger.info(f"Uploading report to s3://{bucket}/{key} ({len(csv_bytes)} bytes)")
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=csv_bytes,
        ContentType="text/csv",
    )

    logger.info(f"Report uploaded successfully: s3://{bucket}/{key}")
    return {
        "status": "ok",
        "bucket": bucket,
        "key": key,
        "trigger": trigger,
        "week": week,
        "bytes": len(csv_bytes),
    }
