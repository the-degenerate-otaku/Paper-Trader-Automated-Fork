from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from paper_trader.config import Settings
from paper_trader.storage import Database
from paper_trader.universe import UniverseService, UniverseUnavailable, parse_constituents

HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"
FIRST = HEADER + "Alpha Ltd,Banking,ALPHA,EQ,INE000A01010\n"
SECOND = HEADER + "Beta Ltd,Banking,BETA,EQ,INE000B01010\n"


@contextmanager
def service_for(
    settings: Settings, database: Database, bodies: list[str], clock: list[datetime]
) -> Iterator[UniverseService]:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=bodies.pop(0), request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        yield UniverseService(settings, database, client, clock=lambda: clock[0])


def test_membership_never_looks_ahead(settings: Settings, database: Database) -> None:
    first = datetime(2026, 10, 19, 10, tzinfo=UTC)
    clock = [first]
    with service_for(settings, database, [FIRST, SECOND], clock) as service:
        service.refresh("NIFTY50")
        with pytest.raises(UniverseUnavailable):
            service.as_of("NIFTY50", first - timedelta(microseconds=1))
        clock[0] += timedelta(days=8)
        service.refresh("NIFTY50")
        assert service.as_of("NIFTY50", first).symbols == ("ALPHA",)
        assert service.as_of("NIFTY50", clock[0]).symbols == ("BETA",)
        assert service.as_of("NIFTY50", first + timedelta(days=7)).stale
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM universe_snapshots").fetchone()[0] == 2


def test_recent_cache_makes_no_network_call(settings: Settings, database: Database) -> None:
    clock = [datetime(2026, 10, 19, tzinfo=UTC)]
    with service_for(settings, database, [FIRST], clock) as service:
        first = service.refresh("NIFTY50")
        clock[0] += timedelta(days=1)
        assert service.refresh("NIFTY50") == first


def test_bad_refresh_keeps_last_snapshot_and_exposes_error(
    settings: Settings, database: Database
) -> None:
    clock = [datetime(2026, 10, 19, tzinfo=UTC)]
    with service_for(settings, database, [FIRST, "<html>blocked</html>"], clock) as service:
        service.refresh("NIFTY50")
        clock[0] += timedelta(days=8)
        result = service.refresh("NIFTY50")
        assert result.symbols == ("ALPHA",)
        assert result.stale and result.error
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM universe_snapshots").fetchone()[0] == 1


def test_disconnect_without_cache_fails_closed(settings: Settings, database: Database) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(UniverseUnavailable, match="ConnectError"):
            UniverseService(settings, database, client).refresh("NIFTY50")


@pytest.mark.parametrize(
    "text",
    [
        "",
        HEADER,
        FIRST + FIRST.splitlines()[1],
        FIRST.replace("EQ", "BE"),
        FIRST.replace("ALPHA", "ALPHA.NS"),
    ],
)
def test_invalid_csv_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        parse_constituents(text, ["EQ"])


def test_naive_asof_rejected(settings: Settings, database: Database) -> None:
    with service_for(settings, database, [], [datetime.now(UTC)]) as service:
        with pytest.raises(ValueError, match="timezone-aware"):
            service.as_of("NIFTY50", datetime(2026, 10, 19))
