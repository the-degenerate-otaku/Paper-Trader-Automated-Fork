from datetime import datetime

import pytest

from paper_trader.calendar import TradingCalendar
from paper_trader.config import Settings, SpecialSession


@pytest.mark.parametrize(
    ("stamp", "phase", "decide", "entry", "squareoff"),
    [
        ("2026-10-19T08:59:59+05:30", "closed", False, False, False),
        ("2026-10-19T09:00:00+05:30", "pre_open", False, False, False),
        ("2026-10-19T09:15:00+05:30", "open", False, False, False),
        ("2026-10-19T09:20:00+05:30", "open", True, True, False),
        ("2026-10-19T15:00:00+05:30", "open", True, False, False),
        ("2026-10-19T15:15:00+05:30", "open", True, False, True),
        ("2026-10-19T15:20:00+05:30", "open", False, False, True),
        ("2026-10-19T15:30:00+05:30", "closed", False, False, True),
        ("2026-10-20T11:00:00+05:30", "holiday", False, False, False),
        ("2026-10-18T11:00:00+05:30", "weekend", False, False, False),
        ("2027-01-04T11:00:00+05:30", "unknown_calendar", False, False, False),
        ("2026-10-19T03:50:00+00:00", "open", True, True, False),
    ],
)
def test_boundaries(
    settings: Settings, stamp: str, phase: str, decide: bool, entry: bool, squareoff: bool
) -> None:
    result = TradingCalendar.load(settings).status(datetime.fromisoformat(stamp))
    assert (result.phase, result.can_decide, result.can_enter_mis, result.must_squareoff_mis) == (
        phase,
        decide,
        entry,
        squareoff,
    )


def test_rejects_naive_timestamp(settings: Settings) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TradingCalendar.load(settings).status(datetime(2026, 10, 19, 10))


def test_explicit_muhurat_session_overrides_sunday_holiday(settings: Settings) -> None:
    calendar = TradingCalendar.load(settings)
    calendar.calendar.special_sessions = [
        SpecialSession.model_validate(
            {
                "date": "2026-11-08",
                "open": "18:00",
                "close": "19:00",
                "last_entry": "18:30",
                "mis_squareoff": "18:45",
                "name": "Test special session",
            }
        )
    ]
    result = calendar.status(datetime.fromisoformat("2026-11-08T18:10:00+05:30"))
    assert result.can_enter_mis
    assert not calendar.status(datetime.fromisoformat("2026-11-08T09:30:00+05:30")).can_decide
