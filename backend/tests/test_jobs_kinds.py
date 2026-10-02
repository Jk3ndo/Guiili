from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.services.jobs.kinds import schedule_offset, slot_start

A = UUID("11111111-1111-1111-1111-111111111111")
B = UUID("22222222-2222-2222-2222-222222222222")
DAY = timedelta(days=1)


def test_schedule_offset_is_stable_and_within_the_interval() -> None:
    offset = schedule_offset(A, DAY)
    assert timedelta(0) <= offset < DAY
    assert schedule_offset(A, DAY) == offset


def test_schedule_offset_differs_between_schedules() -> None:
    assert schedule_offset(A, DAY) != schedule_offset(B, DAY)


def test_schedule_offset_scales_with_the_interval() -> None:
    eight_hours = timedelta(hours=8)
    assert timedelta(0) <= schedule_offset(A, eight_hours) < eight_hours


def test_slot_start_without_offset_is_the_unix_grid() -> None:
    now = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)
    assert slot_start(now, DAY) == datetime(2026, 9, 26, tzinfo=UTC)


def test_slot_start_with_an_offset_shifts_the_grid() -> None:
    now = datetime(2026, 9, 26, 6, 7, tzinfo=UTC)
    assert slot_start(now, DAY, offset=timedelta(hours=3)) == datetime(2026, 9, 26, 3, tzinfo=UTC)


def test_slot_start_before_the_shifted_boundary_stays_in_the_previous_slot() -> None:
    now = datetime(2026, 9, 26, 1, 0, tzinfo=UTC)
    assert slot_start(now, DAY, offset=timedelta(hours=3)) == datetime(2026, 9, 25, 3, tzinfo=UTC)
