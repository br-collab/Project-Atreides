from __future__ import annotations

import csv
import io
import json
import re
import shutil
import zipfile
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from atreides.deadlines.calendar import CalendarIndeterminateError, Market, MarketCalendar
from marketdata.catalog import resolve_source
from marketdata.model import Source
from marketdata.store import digest_file, initialize, latest_raw

IDENTIFIER = re.compile(r"(?:^|_)(?:cusip|figi|ticker|issuer(?:_name)?)(?:$|_)", re.I)
ALLOWED_UNITS = frozenset({"percent", "basis_points", "usd", "count", "ratio"})
RATE_MIN = Decimal("-10")
RATE_MAX = Decimal("100")


def _decimal(value: object, label: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError) as error:
        raise ValueError(f"invalid numeric value for {label}: {value!r}") from error


def _iso_date(value: object) -> str:
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"invalid observation date: {text}")


def _treasury_rows(raw: bytes, source: Source) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    for item in reader:
        observation_date = _iso_date(item.get("Date"))
        for column, value in item.items():
            if column == "Date" or value in {None, ""}:
                continue
            rows.append(_row(observation_date, column, _decimal(value, column), "percent", source))
    return rows


def _nyfed_rows(raw: bytes, source: Source) -> list[dict[str, object]]:
    document = json.loads(raw)
    candidates = document.get("refRates") or document.get("rates") or document.get("data")
    if not isinstance(candidates, list):
        raise ValueError("NY Fed response lacks a published-rate row list")
    rows: list[dict[str, object]] = []
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError("NY Fed published-rate row is not an object")
        rate = item.get("percentRate", item.get("rate"))
        rate_type = str(item.get("type", item.get("rateType", "SOFR"))).upper()
        rows.append(
            _row(
                _iso_date(item.get("effectiveDate", item.get("date"))),
                rate_type,
                _decimal(rate, rate_type),
                "percent",
                source,
            )
        )
    return rows


def _fiscal_rows(raw: bytes, source: Source) -> list[dict[str, object]]:
    document = json.loads(raw)
    candidates = document.get("data")
    if not isinstance(candidates, list):
        raise ValueError("Fiscal Data response lacks data rows")
    rows: list[dict[str, object]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        clean = {key: value for key, value in item.items() if not IDENTIFIER.search(key)}
        observation_date = clean.get("auction_date") or clean.get("record_date")
        for key, value in clean.items():
            if key.endswith(("_amt", "_count")) and value not in {None, ""}:
                unit = "usd" if key.endswith("_amt") else "count"
                rows.append(
                    _row(_iso_date(observation_date), key, _decimal(value, key), unit, source)
                )
    if not rows:
        raise ValueError("Fiscal Data response has no admitted numeric observations")
    return rows


def _ofr_rows(raw: bytes, source: Source) -> list[dict[str, object]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames and any(IDENTIFIER.search(name) for name in reader.fieldnames):
        raise ValueError("OFR input contains an identifier column")
    rows: list[dict[str, object]] = []
    for item in reader:
        observation_date = item.get("date") or item.get("Date")
        for key, value in item.items():
            if key.lower() == "date" or value in {None, ""}:
                continue
            rows.append(_row(_iso_date(observation_date), key, _decimal(value, key), "usd", source))
    return rows


def _sec_rows(raw: bytes, source: Source) -> list[dict[str, object]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [name for name in archive.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise ValueError("SEC fails archive must contain one data file")
        text = archive.read(names[0]).decode("utf-8-sig")
    by_date: dict[str, Decimal] = defaultdict(Decimal)
    reader = csv.DictReader(io.StringIO(text), delimiter="|")
    for item in reader:
        by_date[_iso_date(item.get("SETTLEMENT DATE"))] += _decimal(
            item.get("QUANTITY (FAILS)"), "fails quantity"
        )
    return [
        _row(day, "aggregate_fail_quantity", quantity, "count", source)
        for day, quantity in sorted(by_date.items())
    ]


def _row(
    observation_date: str,
    metric: str,
    value: Decimal,
    unit: str,
    source: Source,
) -> dict[str, object]:
    return {
        "date": observation_date,
        "metric": metric,
        "value": value,
        "unit": unit,
        "source_id": source.source_id,
        "source_url": source.url,
        "citation": source.citation,
        "license_class": source.license_class,
        "ny_fed_notice": source.ny_fed_notice,
    }


PARSERS = {
    "treasury_yield_csv": _treasury_rows,
    "nyfed_rate_json": _nyfed_rows,
    "fiscal_json": _fiscal_rows,
    "ofr_csv": _ofr_rows,
    "sec_ftd": _sec_rows,
}


def validate_rows(rows: list[dict[str, object]]) -> list[str]:
    errors: list[str] = []
    seen: dict[tuple[str, str], Decimal] = {}
    dates: set[date] = set()
    metrics: set[str] = set()
    for row in rows:
        missing = {"date", "metric", "value", "unit", "source_id", "license_class"} - row.keys()
        if missing:
            errors.append(f"missing columns: {sorted(missing)}")
            continue
        if any(IDENTIFIER.search(str(key)) for key in row):
            errors.append("identifier-shaped column in normalized row")
        unit = str(row["unit"])
        if unit not in ALLOWED_UNITS:
            errors.append(f"invalid unit: {unit}")
        value = Decimal(str(row["value"]))
        metric = str(row["metric"])
        if unit == "percent" and not RATE_MIN <= value <= RATE_MAX:
            errors.append(f"percent out of range: {metric}={value}")
        key = (str(row["date"]), metric)
        if key in seen and seen[key] != value:
            errors.append(f"duplicate key with differing values: {key}")
        seen[key] = value
        dates.add(date.fromisoformat(str(row["date"])))
        metrics.add(metric)
    if dates:
        date_sets = {
            metric: {
                date.fromisoformat(str(row["date"])) for row in rows if row["metric"] == metric
            }
            for metric in metrics
        }
        if len({frozenset(values) for values in date_sets.values()}) > 1:
            errors.append("calendar completeness differs between metrics")
        # DATA-1 stores Treasury and overnight-funding observations. Their
        # publication completeness follows the government-securities/federal-
        # banking calendar, not an equity exchange calendar.
        calendar = MarketCalendar.load(Market.US_GOVERNMENT_SECURITIES)
        start, end = min(dates), max(dates)
        for metric in metrics:
            metric_dates = date_sets[metric]
            cursor = start
            while cursor <= end:
                try:
                    business_day = calendar.is_business_day(cursor)
                except CalendarIndeterminateError as error:
                    errors.append(str(error))
                    break
                if business_day and cursor not in metric_dates:
                    errors.append(f"calendar gap: {metric} {cursor.isoformat()}")
                cursor = cursor.fromordinal(cursor.toordinal() + 1)
    return sorted(set(errors))


def normalize(source_id: str, *, root: Path | None = None) -> Path:
    paths = initialize(root)
    source = resolve_source(source_id)
    raw_path = latest_raw(source, paths)
    try:
        rows = PARSERS[source.kind](raw_path.read_bytes(), source)
        errors = validate_rows(rows)
        table = pa.Table.from_pylist(rows)
        destination = paths.normalized / f"{source_id}-{digest_file(raw_path)[:16]}.parquet"
        pq.write_table(table, destination)
        metadata = {
            "schema_version": "cfma.normalized/1",
            "source_id": source_id,
            "source_url": source.url,
            "license_class": source.license_class,
            "ny_fed_notice": source.ny_fed_notice,
            "raw_sha256": digest_file(raw_path),
            "sha256": digest_file(destination),
            "row_count": len(rows),
            "validation_status": "clean" if not errors else "unclean",
            "validation_errors": errors,
        }
        destination.with_suffix(".metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n"
        )
        if errors:
            shutil.copy2(destination, paths.quarantine / destination.name)
        return destination
    except Exception as error:
        (paths.quarantine / f"normalize-{source_id}.json").write_text(
            json.dumps({"source_id": source_id, "reason": str(error)}, indent=2) + "\n"
        )
        raise


def reconcile(paths: list[Path], *, tolerance: Decimal = Decimal("0.01")) -> list[str]:
    """Compare only admitted normalized sources where date, metric and unit overlap."""
    observations: dict[tuple[str, str, str], list[tuple[str, Decimal]]] = defaultdict(list)
    for path in paths:
        for row in pq.read_table(path).to_pylist():
            observations[(row["date"], row["metric"], row["unit"])].append(
                (row["source_id"], Decimal(str(row["value"])))
            )
    errors: list[str] = []
    for key, values in observations.items():
        if len({source for source, _ in values}) > 1:
            spread = max(value for _, value in values) - min(value for _, value in values)
            if spread > tolerance:
                errors.append(f"cross-source mismatch {key}: spread {spread}")
    return errors
