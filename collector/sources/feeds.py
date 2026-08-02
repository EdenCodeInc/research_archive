"""Vendor, lab, and publication feeds (RSS/Atom) via feedparser."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, timezone

import feedparser

from .. import config
from ..http import get
from ..relevance import is_relevant

log = logging.getLogger(__name__)

_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str, limit: int = 2000) -> str:
    text = re.sub(r"\s+", " ", _TAGS.sub(" ", text or "")).strip()
    return text[:limit]


def _entry_date(item) -> date | None:
    for field in ("published_parsed", "updated_parsed"):
        parsed = item.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc).date()
            except (TypeError, ValueError):
                continue
    return None


def _summary(item) -> str:
    contents = item.get("content") or []
    if contents:
        return _clean(contents[0].get("value", ""))
    return _clean(item.get("summary", ""))


def _fetch_feed(name: str, url: str, needs_filter: bool, since: date) -> list[dict]:
    response = get(url)
    if response is None:
        return []

    parsed = feedparser.parse(response.content)
    if parsed.bozo and not parsed.entries:
        log.warning("feed %s: unparseable (%s)", name, parsed.get("bozo_exception"))
        return []

    entries = []
    for item in parsed.entries:
        published = _entry_date(item)
        if published is None or published < since:
            continue

        title = _clean(item.get("title", ""), limit=400)
        link = item.get("link", "")
        if not title or not link:
            continue

        body = _summary(item)
        if needs_filter and not is_relevant(title, body):
            continue

        # Feed items rarely carry a stable guid across all publishers, so hash
        # the canonical link — it survives title edits and guid churn.
        digest = hashlib.sha1(link.encode("utf-8")).hexdigest()[:16]

        entries.append(
            {
                "id": f"feed:{digest}",
                "title": title,
                "url": link,
                "abstract": body,
                "authors": [a.get("name", "") for a in item.get("authors", []) if a.get("name")],
                "published": published.isoformat(),
                "source": name,
                "source_kind": "blog",
                "extra": {"feed_url": url},
            }
        )
    return entries


def fetch(since: date) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()

    for name, url, needs_filter in config.FEEDS:
        log.info("feed: fetching %s", name)
        for entry in _fetch_feed(name, url, needs_filter, since):
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            results.append(entry)

    log.info("feeds: %d entries", len(results))
    return results
