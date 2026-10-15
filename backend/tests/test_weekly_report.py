"""Tests for the weekly meetings report generator."""

from datetime import date, datetime, time

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Meeting, Participant, User
from app.reports.weekly import (
    build_weekly_report,
    generate_weekly_report,
    get_previous_iso_week,
    get_report_s3_key,
    get_week_boundaries,
    parse_iso_week,
)


def test_parse_iso_week():
    year, week = parse_iso_week("2026-W40")
    assert year == 2026
    assert week == 40

    year, week = parse_iso_week("2025-W01")
    assert year == 2025
    assert week == 1

    with pytest.raises(ValueError, match="Invalid ISO week format"):
        parse_iso_week("invalid")

    with pytest.raises(ValueError, match="Invalid ISO week format"):
        parse_iso_week("2026-40")

    with pytest.raises(ValueError, match="Invalid ISO week number"):
        parse_iso_week("2026-W55")


def test_week_boundaries():
    week_start, week_end, prev_str, prev_start, prev_end = get_week_boundaries("2026-W41")
    # 2026-W41 starts on Monday 2026-10-05 and ends on Monday 2026-10-12
    assert week_start.strftime("%Y-%m-%d") == "2026-10-05"
    assert week_end.strftime("%Y-%m-%d") == "2026-10-12"
    assert prev_str == "2026-W40"
    assert prev_start.strftime("%Y-%m-%d") == "2026-09-28"
    assert prev_end.strftime("%Y-%m-%d") == "2026-10-05"


def test_get_previous_iso_week():
    ref = date(2026, 10, 15)  # Thursday of 2026-W42
    # 7 days ago is 2026-10-08 (2026-W41)
    prev = get_previous_iso_week(ref)
    assert prev == "2026-W41"


def test_get_report_s3_key():
    assert get_report_s3_key("2026-W40") == "reports/2026-W40.csv"
    assert get_report_s3_key("2026-W01") == "reports/2026-W01.csv"


@pytest_asyncio.fixture
async def sample_meetings_data(session: AsyncSession):
    # Setup test users
    u1 = User(id="user_1", name="Alice Wonderland", email="alice@example.com")
    u2 = User(id="user_2", name="Bob Builder", email="bob@example.com")
    session.add_all([u1, u2])
    await session.commit()

    # 2026-W41: Monday Oct 5 to Sunday Oct 11, 2026
    t1 = datetime.combine(date(2026, 10, 5), time(10, 0), tzinfo=settings.tz)
    t2 = datetime.combine(date(2026, 10, 5), time(11, 30), tzinfo=settings.tz)  # 1.5h
    m1 = Meeting(
        owner_id="user_1",
        name="Sprint Planning",
        starts_at=t1,
        ends_at=t2,
        participants=[
            Participant(name="Alice Wonderland", email="alice@example.com", position=0),
            Participant(name="Charlie", email="charlie@example.com", position=1),
        ],
    )

    t3 = datetime.combine(date(2026, 10, 6), time(14, 0), tzinfo=settings.tz)
    t4 = datetime.combine(date(2026, 10, 6), time(16, 0), tzinfo=settings.tz)  # 2.0h
    m2 = Meeting(
        owner_id="user_2",
        name="Architecture Review",
        starts_at=t3,
        ends_at=t4,
        participants=[
            Participant(name="Bob Builder", email="bob@example.com", position=0),
            Participant(name="Charlie", email="charlie@example.com", position=1),
        ],
    )

    # Previous week (2026-W40): Oct 1, 2026 (1 hour meeting)
    t_prev_1 = datetime.combine(date(2026, 10, 1), time(9, 0), tzinfo=settings.tz)
    t_prev_2 = datetime.combine(date(2026, 10, 1), time(10, 0), tzinfo=settings.tz)  # 1.0h
    m_prev = Meeting(
        owner_id="user_1",
        name="Past Retrospective",
        starts_at=t_prev_1,
        ends_at=t_prev_2,
        participants=[Participant(name="Alice Wonderland", position=0)],
    )

    session.add_all([m1, m2, m_prev])
    await session.commit()


@pytest.mark.asyncio
async def test_generate_weekly_report_with_data(session: AsyncSession, sample_meetings_data):
    csv_bytes = await generate_weekly_report("2026-W41", session=session)
    content = csv_bytes.decode("utf-8")

    # Check headers and summary
    assert "=== WEEKLY MEETINGS REPORT ===" in content
    assert "Week,2026-W41" in content
    assert "Total Meetings,2,1,+1" in content
    assert "Total Duration (hours),3.50,1.00,+2.50" in content

    # Check top meetings
    assert "Architecture Review" in content
    assert "Sprint Planning" in content

    # Check organiser breakdown
    assert "Alice Wonderland,alice@example.com,1,1.50" in content
    assert "Bob Builder,bob@example.com,1,2.00" in content

    # Check participant breakdown
    assert "Charlie,charlie@example.com,2,3.50" in content


@pytest.mark.asyncio
async def test_generate_weekly_report_empty_week(session: AsyncSession):
    csv_bytes = await generate_weekly_report("2026-W30", session=session)
    content = csv_bytes.decode("utf-8")

    assert "Total Meetings,0,0,0" in content
    assert "Total Duration (hours),0.00,0.00,0.00" in content
    assert "No meetings recorded for this week" in content


def test_build_weekly_report_sync():
    # Calling the sync wrapper function
    csv_bytes = build_weekly_report("2026-W30")
    assert isinstance(csv_bytes, bytes)
    assert b"=== WEEKLY MEETINGS REPORT ===" in csv_bytes
