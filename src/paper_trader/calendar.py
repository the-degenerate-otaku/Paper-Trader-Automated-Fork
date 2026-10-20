from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

import yaml

from paper_trader.config import CalendarFile, Settings


@dataclass(frozen=True)
class SessionStatus:
    phase: Literal["unknown_calendar", "holiday", "weekend", "pre_open", "open", "closed"]
    can_decide: bool
    can_enter_mis: bool
    must_squareoff_mis: bool
    reason: str


class TradingCalendar:
    def __init__(self, settings: Settings, calendar: CalendarFile) -> None:
        self.settings = settings
        self.calendar = calendar
        self.zone = ZoneInfo(settings.account.timezone)

    @classmethod
    def load(cls, settings: Settings) -> TradingCalendar:
        content = yaml.safe_load(settings.session.calendar_path.read_text(encoding="utf-8"))
        return cls(settings, CalendarFile.model_validate(content))

    def status(self, timestamp: datetime) -> SessionStatus:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Timestamp must be timezone-aware")
        local = timestamp.astimezone(self.zone)
        day = local.date()
        if day.year not in self.calendar.covered_years:
            return SessionStatus(
                "unknown_calendar", False, False, False, "Unverified calendar year"
            )
        special = next((s for s in self.calendar.special_sessions if s.date == day), None)
        session = special or self.settings.session
        if special is None:
            if day in self.calendar.holidays:
                return SessionStatus("holiday", False, False, False, self.calendar.holidays[day])
            if day.weekday() not in self.settings.session.weekdays:
                return SessionStatus("weekend", False, False, False, "Non-trading weekday")
        opening = datetime.combine(day, session.open, self.zone)
        closing = datetime.combine(day, session.close, self.zone)
        squareoff = datetime.combine(day, session.mis_squareoff, self.zone)
        last_entry = datetime.combine(day, session.last_entry, self.zone)
        if local >= closing:
            return SessionStatus("closed", False, False, True, "Session ended; MIS exit overdue")
        if local < opening:
            pre_open = datetime.combine(day, self.settings.session.pre_open, self.zone)
            phase: Literal["pre_open", "closed"] = (
                "pre_open" if special is None and local >= pre_open else "closed"
            )
            return SessionStatus(phase, False, False, False, "Continuous session has not opened")
        active_start = opening + timedelta(minutes=self.settings.session.skip_first_minutes)
        active_end = closing - timedelta(minutes=self.settings.session.skip_last_minutes)
        can_decide = active_start <= local < active_end
        return SessionStatus(
            "open",
            can_decide,
            can_decide and local < last_entry,
            local >= squareoff,
            special.name if special else "Continuous session",
        )

    def holiday_rows(self) -> list[tuple[str, str, str]]:
        return [
            (day.isoformat(), name, self.calendar.source)
            for day, name in sorted(self.calendar.holidays.items())
        ]

    def is_covered(self, day: date) -> bool:
        return day.year in self.calendar.covered_years
