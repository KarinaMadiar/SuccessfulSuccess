"""Weekly meetings report generation.

Queries meetings for a given ISO week and formats the insights as CSV bytes.
Pure business logic: decoupled from AWS triggers and delivery mechanisms.
"""

import asyncio
import csv
import io
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import SessionFactory
from app.models import Meeting, User

WEEK_REGEX = re.compile(r"^(\d{4})-W(\d{2})$")


def parse_iso_week(week: str) -> tuple[int, int]:
    """Parse and validate an ISO week string (e.g. '2026-W40')."""
    match = WEEK_REGEX.match(week.strip())
    if not match:
        raise ValueError(f"Invalid ISO week format '{week}'. Expected YYYY-Www, e.g. '2026-W40'")
    year, week_num = int(match.group(1)), int(match.group(2))
    if week_num < 1 or week_num > 53:
        raise ValueError(f"Invalid ISO week number {week_num}. Must be between 1 and 53")
    return year, week_num


def get_week_boundaries(week: str) -> tuple[datetime, datetime, str, datetime, datetime]:
    """Return (week_start, week_end, prev_week_str, prev_week_start, prev_week_end).

    All timestamps are timezone-aware using settings.tz.
    """
    year, week_num = parse_iso_week(week)
    monday = date.fromisocalendar(year, week_num, 1)
    week_start = datetime.combine(monday, time.min, tzinfo=settings.tz)
    week_end = week_start + timedelta(days=7)

    prev_monday = monday - timedelta(days=7)
    prev_year, prev_week_num, _ = prev_monday.isocalendar()
    prev_week_str = f"{prev_year}-W{prev_week_num:02d}"
    prev_week_start = week_start - timedelta(days=7)
    prev_week_end = week_start

    return week_start, week_end, prev_week_str, prev_week_start, prev_week_end


def get_previous_iso_week(reference_date: date | None = None) -> str:
    """Return the previous ISO week string (e.g. '2026-W40') relative to reference_date."""
    if reference_date is None:
        reference_date = datetime.now(settings.tz).date()
    prev_date = reference_date - timedelta(days=7)
    year, week_num, _ = prev_date.isocalendar()
    return f"{year}-W{week_num:02d}"


def get_report_s3_key(week: str) -> str:
    """Return the deterministic, idempotent S3 object key for a given ISO week."""
    # Running twice for one week overwrites the same file in place
    return f"reports/{week}.csv"


async def generate_weekly_report(week: str, session: AsyncSession | None = None) -> bytes:
    """Query the database and assemble the CSV report for the specified ISO week."""
    week_start, week_end, prev_week_str, prev_week_start, prev_week_end = get_week_boundaries(week)

    if session is not None:
        return await _query_and_render(
            week, week_start, week_end, prev_week_str, prev_week_start, prev_week_end, session
        )

    async with SessionFactory() as new_session:
        return await _query_and_render(
            week, week_start, week_end, prev_week_str, prev_week_start, prev_week_end, new_session
        )


async def _query_and_render(
    week: str,
    week_start: datetime,
    week_end: datetime,
    prev_week_str: str,
    prev_week_start: datetime,
    prev_week_end: datetime,
    session: AsyncSession,
) -> bytes:
    # 1. Fetch current week's meetings with participants
    current_stmt = (
        select(Meeting)
        .options(selectinload(Meeting.participants))
        .where(Meeting.starts_at >= week_start, Meeting.starts_at < week_end)
        .order_by(Meeting.starts_at.asc())
    )
    current_meetings = list((await session.scalars(current_stmt)).all())

    # 2. Fetch previous week's meetings for comparison
    prev_stmt = select(Meeting).where(
        Meeting.starts_at >= prev_week_start, Meeting.starts_at < prev_week_end
    )
    prev_meetings = list((await session.scalars(prev_stmt)).all())

    # 3. Fetch users to map owner_id to user name/email
    users_stmt = select(User)
    users = list((await session.scalars(users_stmt)).all())
    user_map = {u.id: u for u in users}

    # Calculations
    total_meetings = len(current_meetings)
    total_seconds = sum((m.ends_at - m.starts_at).total_seconds() for m in current_meetings)
    total_hours = total_seconds / 3600.0

    prev_meetings_count = len(prev_meetings)
    prev_seconds = sum((m.ends_at - m.starts_at).total_seconds() for m in prev_meetings)
    prev_hours = prev_seconds / 3600.0

    delta_meetings = total_meetings - prev_meetings_count
    delta_hours = total_hours - prev_hours

    # Top 5 longest meetings
    top_meetings = sorted(
        current_meetings,
        key=lambda m: (m.ends_at - m.starts_at).total_seconds(),
        reverse=True,
    )[:5]

    # Breakdown by organiser
    organiser_stats: dict[str, dict[str, Any]] = {}
    for m in current_meetings:
        oid = m.owner_id or "unassigned"
        u = user_map.get(oid)
        name = u.name if u and u.name else (oid if oid != "unassigned" else "Unassigned")
        email = u.email if u and u.email else ""
        dur = (m.ends_at - m.starts_at).total_seconds() / 3600.0

        if oid not in organiser_stats:
            organiser_stats[oid] = {"name": name, "email": email, "count": 0, "hours": 0.0}
        organiser_stats[oid]["count"] += 1
        organiser_stats[oid]["hours"] += dur

    sorted_organisers = sorted(
        organiser_stats.values(), key=lambda x: (x["hours"], x["count"]), reverse=True
    )

    # Breakdown by participant
    participant_stats: dict[tuple[str, str], dict[str, Any]] = {}
    for m in current_meetings:
        dur = (m.ends_at - m.starts_at).total_seconds() / 3600.0
        for p in m.participants:
            key = (p.name, p.email or "")
            if key not in participant_stats:
                participant_stats[key] = {
                    "name": p.name,
                    "email": p.email or "",
                    "count": 0,
                    "hours": 0.0,
                }
            participant_stats[key]["count"] += 1
            participant_stats[key]["hours"] += dur

    sorted_participants = sorted(
        participant_stats.values(), key=lambda x: (x["hours"], x["count"]), reverse=True
    )

    # Render CSV
    out = io.StringIO()
    writer = csv.writer(out)

    writer.writerow(["=== WEEKLY MEETINGS REPORT ==="])
    writer.writerow(["Week", week])
    writer.writerow(["Timezone", str(settings.tz)])
    writer.writerow(
        [
            "Period",
            f"{week_start.strftime('%Y-%m-%d %H:%M')} to {week_end.strftime('%Y-%m-%d %H:%M')}",
        ]
    )
    writer.writerow([])

    # Summary section
    writer.writerow(["--- SUMMARY ---"])
    writer.writerow(["Metric", f"Week {week}", f"Previous Week ({prev_week_str})", "Change"])
    writer.writerow(
        [
            "Total Meetings",
            total_meetings,
            prev_meetings_count,
            f"{'+' if delta_meetings > 0 else ''}{delta_meetings}",
        ]
    )
    writer.writerow(
        [
            "Total Duration (hours)",
            f"{total_hours:.2f}",
            f"{prev_hours:.2f}",
            f"{'+' if delta_hours > 0 else ''}{delta_hours:.2f}",
        ]
    )
    writer.writerow([])

    # Top 5 longest meetings
    writer.writerow(["--- TOP 5 LONGEST MEETINGS ---"])
    writer.writerow(["Rank", "Title", "Start Time", "Duration (minutes)", "Participants Count"])
    if top_meetings:
        for rank, m in enumerate(top_meetings, start=1):
            dur_min = (m.ends_at - m.starts_at).total_seconds() / 60.0
            start_str = m.starts_at.astimezone(settings.tz).strftime("%Y-%m-%d %H:%M")
            writer.writerow([rank, m.name, start_str, f"{dur_min:.1f}", len(m.participants)])
    else:
        writer.writerow(["No meetings recorded for this week"])
    writer.writerow([])

    # Organiser breakdown
    writer.writerow(["--- BREAKDOWN BY ORGANISER ---"])
    writer.writerow(["Organiser", "Email", "Meetings Count", "Total Duration (hours)"])
    if sorted_organisers:
        for org in sorted_organisers:
            writer.writerow([org["name"], org["email"], org["count"], f"{org['hours']:.2f}"])
    else:
        writer.writerow(["No organisers recorded for this week"])
    writer.writerow([])

    # Participant breakdown
    writer.writerow(["--- BREAKDOWN BY PARTICIPANT ---"])
    writer.writerow(["Participant Name", "Email", "Meetings Count", "Total Hours"])
    if sorted_participants:
        for part in sorted_participants:
            writer.writerow([part["name"], part["email"], part["count"], f"{part['hours']:.2f}"])
    else:
        writer.writerow(["No participants recorded for this week"])

    return out.getvalue().encode("utf-8")


async def _build_with_standalone_engine(week: str) -> bytes:
    from sqlalchemy.pool import NullPool

    standalone_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(standalone_engine, expire_on_commit=False, autoflush=False)
    try:
        async with session_factory() as session:
            return await generate_weekly_report(week, session=session)
    finally:
        await standalone_engine.dispose()


def build_weekly_report(week: str) -> bytes:
    """Query the meetings of one ISO week (e.g. '2026-W40') and return the CSV.

    Synchronous interface compatible with Lambda handlers and scripts.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_build_with_standalone_engine(week))).result()
    return asyncio.run(_build_with_standalone_engine(week))
