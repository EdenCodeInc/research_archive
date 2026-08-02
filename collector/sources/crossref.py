"""Peer-reviewed journal articles via the Crossref REST API.

https://api.crossref.org/swagger-ui/index.html

We query per-ISSN against a small set of journals dedicated to quantum
information, so no relevance filtering is needed — everything they publish is
on topic.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from .. import config
from ..http import get

log = logging.getLogger(__name__)

API_URL = "https://api.crossref.org/works"

_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub(" ", text or "")).strip()


def _issued_date(item: dict) -> date | None:
    """Crossref date-parts look like [[2026, 7, 14]] and may omit day/month."""
    for field in ("published-online", "published-print", "issued", "created"):
        parts = (item.get(field) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            nums = list(parts[0]) + [1, 1]
            try:
                return date(int(nums[0]), int(nums[1]), int(nums[2]))
            except (ValueError, TypeError):
                continue
    return None


def _authors(item: dict) -> list[str]:
    names = []
    for author in item.get("author", []) or []:
        given = author.get("given", "")
        family = author.get("family", "")
        name = f"{given} {family}".strip() or author.get("name", "")
        if name:
            names.append(name)
    return names


def _fetch_issn(issn: str, journal: str, since: date) -> list[dict]:
    params = {
        "filter": f"issn:{issn},from-pub-date:{since.isoformat()}",
        "rows": config.CROSSREF_ROWS,
        "sort": "published",
        "order": "desc",
        "select": "DOI,title,abstract,author,published-online,published-print,"
        "issued,created,URL,container-title,subject",
    }
    # Crossref rejects an empty mailto; omit it entirely when unset. Requests
    # without one still work, just on the slower shared pool.
    if config.CONTACT_EMAIL:
        params["mailto"] = config.CONTACT_EMAIL
    response = get(API_URL, params=params)
    if response is None:
        return []

    try:
        items = response.json()["message"]["items"]
    except (ValueError, KeyError) as exc:
        log.warning("Crossref: unexpected response for %s (%s)", journal, exc)
        return []

    entries = []
    for item in items:
        published = _issued_date(item)
        if published is None or published < since:
            continue
        titles = item.get("title") or []
        title = _clean(titles[0]) if titles else ""
        if not title:
            continue
        doi = item.get("DOI", "")
        containers = item.get("container-title") or [journal]
        entries.append(
            {
                "id": f"doi:{doi}" if doi else f"crossref:{title[:80]}",
                "title": title,
                "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                # Crossref abstracts are JATS XML when present at all; strip the
                # markup and accept that many publishers deposit nothing.
                "abstract": _clean(item.get("abstract", "")),
                "authors": _authors(item),
                "published": published.isoformat(),
                "source": _clean(containers[0]),
                "source_kind": "journal",
                "extra": {"doi": doi, "subjects": item.get("subject", []) or []},
            }
        )
    return entries


def fetch(since: date) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()

    for issn, journal in config.CROSSREF_ISSNS.items():
        log.info("Crossref: fetching %s (%s) since %s", journal, issn, since)
        for entry in _fetch_issn(issn, journal, since):
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            results.append(entry)

    log.info("Crossref: %d entries", len(results))
    return results
