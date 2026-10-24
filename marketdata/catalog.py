from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from marketdata.model import Source

CATALOG_PATH = Path(__file__).with_name("sources.yaml")
ADMITTED_HOSTS = frozenset(
    {
        "home.treasury.gov",
        "api.fiscaldata.treasury.gov",
        "markets.newyorkfed.org",
        "data.financialresearch.gov",
        "www.financialresearch.gov",
        "www.sec.gov",
    }
)
FORBIDDEN_HOSTS = frozenset(
    {
        "fred.stlouisfed.org",
        "alfred.stlouisfed.org",
        "api.stlouisfed.org",
        "www.dtcc.com",
        "dtcc.com",
        "www.finra.org",
        "finra.org",
    }
)
ADMITTED_CLASSES = frozenset({"A", "B"})


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Source]:
    """Load the repository catalog; JSON is deliberately used as valid YAML 1.2."""
    document = json.loads(path.read_text())
    if document.get("schema_version") != "cfma.sources/1":
        raise ValueError("unsupported source catalog schema")
    notices = document.get("notices", {})
    if not isinstance(notices, dict):
        raise ValueError("source catalog notices must be an object")
    sources: dict[str, Source] = {}
    for row in document.get("sources", []):
        source = Source(
            source_id=str(row["id"]),
            url=str(row["url"]),
            license_class=str(row["license_class"]),
            kind=str(row["kind"]),
            citation=str(row["citation"]),
            ny_fed_notice=(
                str(notices[row["notice_id"]])
                if row.get("notice_id") in notices
                else row.get("ny_fed_notice")
            ),
        )
        if source.source_id in sources:
            raise ValueError(f"duplicate source id: {source.source_id}")
        _validate_source(source)
        sources[source.source_id] = source
    if not sources:
        raise ValueError("source catalog is empty")
    return sources


def _validate_source(source: Source) -> None:
    parsed = urlparse(source.url)
    host = (parsed.hostname or "").lower()
    if host in FORBIDDEN_HOSTS or host not in ADMITTED_HOSTS:
        raise ValueError(f"source host refused: {host or '<missing>'}")
    if host == "www.sec.gov" and "/edgar/" in parsed.path.lower():
        raise ValueError("source host refused: SEC EDGAR content is class X")
    if source.license_class not in ADMITTED_CLASSES:
        raise ValueError(f"source class refused: {source.license_class}")
    if source.license_class == "B" and not source.ny_fed_notice:
        raise ValueError("class B source requires the NY Fed notice")


def resolve_source(source_id: str, *, catalog_path: Path = CATALOG_PATH) -> Source:
    try:
        return load_catalog(catalog_path)[source_id]
    except KeyError as error:
        raise ValueError(f"source is not admitted by catalog: {source_id}") from error


def classify_url(url: str, *, catalog_path: Path = CATALOG_PATH) -> Source:
    """Assign class from the exact catalog URL, never caller or file metadata."""
    host = (urlparse(url).hostname or "").lower()
    if host in FORBIDDEN_HOSTS or host not in ADMITTED_HOSTS:
        raise ValueError(f"source host refused: {host or '<missing>'}")
    matches = [source for source in load_catalog(catalog_path).values() if source.url == url]
    if len(matches) != 1:
        raise ValueError("URL is not exactly admitted by the source catalog")
    return matches[0]
