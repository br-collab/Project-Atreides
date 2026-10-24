"""Write the deterministic EQ-1 Atreides publications."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path

from atreides.deadlines.calendar import Market, MarketCalendar
from atreides.equities.scenario import build_equities_publications


def scenario_time(clock: datetime) -> datetime:
    """The latest US equities business day on or before ``clock``, at the same time of day.

    The EQ-1 scenario books trades and settlements on its ``taken_at`` date, and the
    books projection refuses a reserve source settlement date that is not a loaded
    business day. The main-only publication job runs on every merge, including on
    weekends and holidays, so the writer dates the snapshot to the last business day
    instead of failing (Publish equities self-clearing snapshot failed on 24 Oct 2026,
    a Saturday).
    """
    calendar = MarketCalendar.load(Market.US_EQUITIES)
    day = clock.date()
    while not calendar.is_business_day(day):
        day -= timedelta(days=1)
    return datetime.combine(day, clock.timetz())


def write_publications(directory: Path, *, taken_at: datetime) -> tuple[Path, ...]:
    documents = build_equities_publications(taken_at)
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, payload in sorted(documents.items()):
        path = directory / name
        path.write_bytes(payload)
        paths.append(path)
    return tuple(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args(argv)
    write_publications(args.directory, taken_at=scenario_time(datetime.now(UTC)))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
