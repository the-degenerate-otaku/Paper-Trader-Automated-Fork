from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

import httpx

from paper_trader.config import Settings
from paper_trader.storage import Database


class UniverseUnavailable(RuntimeError):
    pass


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class Constituent:
    symbol: str
    name: str
    sector: str
    isin: str
    series: str


@dataclass(frozen=True)
class UniverseSnapshot:
    index_symbol: str
    observed_at: datetime
    symbols: tuple[str, ...]
    stale: bool
    source_url: str
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["observed_at"] = self.observed_at.isoformat()
        return result


def parse_constituents(text: str, allowed_series: list[str]) -> list[Constituent]:
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    required = {"Company Name", "Industry", "Symbol", "Series", "ISIN Code"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError("NSE constituent CSV has missing headers or is not CSV")
    result: list[Constituent] = []
    seen: set[str] = set()
    for row in reader:
        values = {key: (row.get(key) or "").strip() for key in required}
        if not any(values.values()):
            continue
        symbol = values["Symbol"]
        if not all(values.values()) or not re.fullmatch(r"[A-Z0-9&_.-]+", symbol):
            raise ValueError("Invalid or incomplete constituent row")
        if symbol.endswith(".NS") or symbol in seen:
            raise ValueError("Duplicate or provider-formatted NSE symbol")
        if not re.fullmatch(r"IN[A-Z0-9]{10}", values["ISIN Code"]):
            raise ValueError("Invalid Indian ISIN")
        if values["Series"] not in allowed_series:
            raise ValueError("Unexpected NSE series; rejecting incomplete universe")
        seen.add(symbol)
        result.append(
            Constituent(
                symbol,
                values["Company Name"],
                values["Industry"],
                values["ISIN Code"],
                values["Series"],
            )
        )
    if not result:
        raise ValueError("NSE returned an empty constituent list")
    return result


class UniverseService:
    def __init__(
        self,
        settings: Settings,
        database: Database,
        client: httpx.Client,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.settings = settings
        self.database = database
        self.client = client
        self.clock = clock

    def as_of(self, index_symbol: str, at: datetime) -> UniverseSnapshot:
        stamp = utc_iso(at)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM universe_snapshots WHERE index_symbol=? AND observed_at<=? "
                "ORDER BY observed_at DESC LIMIT 1",
                (index_symbol, stamp),
            ).fetchone()
            if row is None:
                raise UniverseUnavailable(f"No {index_symbol} membership observed by {stamp}")
            members = connection.execute(
                "SELECT symbol FROM constituents_history WHERE snapshot_id=? ORDER BY symbol",
                (row["id"],),
            ).fetchall()
            observed = datetime.fromisoformat(row["observed_at"])
            stale = at - observed >= timedelta(days=self.settings.universe.refresh_days)
            return UniverseSnapshot(
                index_symbol,
                observed,
                tuple(m["symbol"] for m in members),
                stale,
                row["source_url"],
            )

    def refresh(self, index_symbol: str, force: bool = False) -> UniverseSnapshot:
        index = self.settings.universe.indices[index_symbol]
        now = self.clock()
        utc_iso(now)
        cached: UniverseSnapshot | None = None
        try:
            cached = self.as_of(index_symbol, now)
        except UniverseUnavailable:
            pass
        if cached is not None and not cached.stale and not force:
            return cached
        try:
            with self.client.stream(
                "GET",
                index.constituents_url,
                timeout=self.settings.universe.timeout_seconds,
                headers={"User-Agent": self.settings.universe.user_agent},
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > self.settings.universe.max_csv_bytes:
                        raise ValueError("Constituent response exceeds configured size limit")
            members = parse_constituents(
                content.decode("utf-8-sig"), self.settings.universe.allowed_series
            )
            observed = self.clock()
            stamp = utc_iso(observed)
            digest = hashlib.sha256(content).hexdigest()
            with self.database.connect() as connection:
                latest = connection.execute(
                    "SELECT MAX(observed_at) FROM universe_snapshots WHERE index_symbol=?",
                    (index_symbol,),
                ).fetchone()[0]
                if latest is not None and stamp <= latest:
                    raise ValueError(
                        "Observation clock must advance; refusing historical overwrite"
                    )
                cursor = connection.execute(
                    "INSERT INTO universe_snapshots "
                    "(index_symbol, observed_at, source_url, content_sha256, member_count) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (index_symbol, stamp, index.constituents_url, digest, len(members)),
                )
                snapshot_id = cursor.lastrowid
                for member in members:
                    connection.execute(
                        "INSERT INTO instruments (symbol, name, sector, isin, series, "
                        "instrument_type, lot_size, tick_size, provider_symbol) "
                        "VALUES (?, ?, ?, ?, ?, 'EQUITY', 1, ?, ?) "
                        "ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, "
                        "sector=excluded.sector, isin=excluded.isin, series=excluded.series",
                        (
                            member.symbol,
                            member.name,
                            member.sector,
                            member.isin,
                            member.series,
                            str(self.settings.execution.tick_size),
                            member.symbol + ".NS",
                        ),
                    )
                    connection.execute(
                        "INSERT INTO constituents_history "
                        "(snapshot_id, symbol, company_name, sector, isin) VALUES (?, ?, ?, ?, ?)",
                        (snapshot_id, member.symbol, member.name, member.sector, member.isin),
                    )
                connection.execute(
                    "INSERT INTO audit_log (created_at, event, payload_json) VALUES (?, ?, ?)",
                    (
                        stamp,
                        "universe_refresh",
                        json.dumps({"index": index_symbol, "sha256": digest}),
                    ),
                )
            return self.as_of(index_symbol, observed)
        except (httpx.HTTPError, ValueError) as exc:
            reason = (
                type(exc).__name__
                if isinstance(exc, httpx.HTTPError)
                else "Invalid constituent response"
            )
            if cached is None:
                raise UniverseUnavailable(f"{index_symbol} refresh failed: {reason}") from exc
            return UniverseSnapshot(
                cached.index_symbol,
                cached.observed_at,
                cached.symbols,
                cached.stale,
                cached.source_url,
                reason,
            )
