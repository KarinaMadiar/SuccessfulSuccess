"""AWS Lambda handler for report-mailer.

Triggered by S3 ObjectCreated events when a new weekly CSV report is uploaded.
Runs outside the VPC with direct internet access to Amazon SES.
Downloads the report CSV from S3, constructs a MIME message with attachment,
and sends it via Amazon SES.
"""

import logging
import os
import urllib.parse
from email.message import EmailMessage
from typing import Any

import boto3

logger = logging.getLogger("reports.mailer")
logger.setLevel(logging.INFO)

AWS_REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))

s3_client = boto3.client("s3", region_name=AWS_REGION)
ses_client = boto3.client("sesv2", region_name=AWS_REGION)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda handler for sending report emails upon S3 upload."""
    if "Records" not in event or not event["Records"]:
        logger.warning("No records found in S3 event")
        return {"status": "no_records"}

    record = event["Records"][0]
    s3_data = record.get("s3", {})
    bucket = s3_data.get("bucket", {}).get("name")
    raw_key = s3_data.get("object", {}).get("key", "")
    key = urllib.parse.unquote_plus(raw_key)

    # Log trigger line required by item 5
    logger.info(
        f"report-mailer triggered: trigger=s3 bucket={bucket} key={key}",
        extra={"trigger": "s3", "bucket": bucket, "key": key},
    )

    if not bucket or not key:
        raise ValueError(f"Missing bucket or key from S3 event: {event}")

    # Guard: never process or write outside or cause recursion
    if not key.startswith("reports/") or not key.endswith(".csv"):
        logger.warning(f"Ignored non-report key: {key}")
        return {"status": "ignored", "key": key}

    filename = key.split("/")[-1]
    week = filename[:-4]  # remove .csv

    logger.info(f"Downloading s3://{bucket}/{key}")
    response = s3_client.get_object(Bucket=bucket, Key=key)
    csv_bytes = response["Body"].read()

    sender = os.environ.get("SENDER_EMAIL", "reports@successful.pp.ua")
    recipients_str = os.environ.get("RECIPIENT_EMAILS", "madiar.pn@ucu.edu.ua")
    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]

    if not recipients:
        raise ValueError("RECIPIENT_EMAILS environment variable contains no valid email addresses")

    # Construct MIME message
    msg = EmailMessage()
    msg["Subject"] = f"Weekly Meetings Report: {week}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(
        f"Hello,\n\n"
        f"Please find attached your weekly meetings report for {week}.\n\n"
        f"This report was generated and delivered automatically by the Event-Driven Architecture "
        f"(EventBridge Scheduler -> SQS -> Lambda Builder -> S3 -> Lambda Mailer -> SES).\n\n"
        f"Best regards,\n"
        f"SuccessfulSuccess Team\n"
    )

    msg.add_attachment(
        csv_bytes,
        maintype="text",
        subtype="csv",
        filename=filename,
    )

    logger.info(f"Sending report email from {sender} to {recipients} via SESv2")
    ses_response = ses_client.send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": recipients},
        Content={"Raw": {"Data": msg.as_bytes()}},
    )

    message_id = ses_response.get("MessageId")
    logger.info(f"Email delivered to SES successfully: MessageId={message_id}")

    return {
        "status": "sent",
        "message_id": message_id,
        "week": week,
        "recipients": recipients,
        "trigger": "s3",
    }
