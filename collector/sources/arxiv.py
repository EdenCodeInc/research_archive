"""arXiv preprints via the official arXiv API (Atom over HTTP).

https://info.arxiv.org/help/api/user-manual.html
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timezone

import feedparser

from .. import config
from ..http import get
from ..relevance import is_relevant

log = logging.getLogger(__name__)

API_URL = "http://export.arxiv.org/api/query"

# arXiv ids look like "http://arxiv.org/abs/2601.01234v2" — strip the host and
# the version suffix so a v1 and a later v3 of the same paper collapse into one
# entry rather than reappearing every time the authors revise it.
_ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5})")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _fetch_category(category: str, since: date) -> list[dict]:
    """Page back through a category until we reach `since` or stop early.

    Returns (entries, status) where status is one of:
      "complete" — the whole requested window was covered
      "capped"   — ARXIV_MAX_RESULTS stopped us first
      "error"    — a request failed, so coverage is unknown

    The caller warns on anything but "complete": a partial window looks exactly
    like a quiet week otherwise, and the two need different fixes.
    """
    entries: list[dict] = []
    start = 0
    page_size = 100
    status = "capped"

    while start < config.ARXIV_MAX_RESULTS:
        params = {
            "search_query": f"cat:{category}",
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": start,
            "max_results": min(page_size, config.ARXIV_MAX_RESULTS - start),
        }
        response = get(API_URL, params=params)
        if response is None:
            status = "error"
            break

        parsed = feedparser.parse(response.content)
        if not parsed.entries:
            # Ran out of results before the window edge — the category simply
            # has nothing older, so the window is fully covered.
            status = "complete"
            break

        for item in parsed.entries:
            published = _parse_date(item.get("published"))
            if published is None:
                continue
            # Results are newest-first, so the first entry older than the
            # window means every remaining entry is too.
            if published < since:
                status = "complete"
                break
            entries.append(_to_entry(item, published, category))

        if status == "complete":
            break

        start += page_size
        time.sleep(config.ARXIV_REQUEST_DELAY)

    return entries, status


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        ).date()
    except ValueError:
        return None


def _to_entry(item, published: date, category: str) -> dict:
    raw_id = item.get("id", "")
    match = _ARXIV_ID.search(raw_id)
    arxiv_id = match.group(1) if match else raw_id

    pdf_url = ""
    for link in item.get("links", []):
        if link.get("title") == "pdf":
            pdf_url = link.get("href", "")

    return {
        "id": f"arxiv:{arxiv_id}",
        "title": _clean(item.get("title", "")),
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "abstract": _clean(item.get("summary", "")),
        "authors": [a.get("name", "") for a in item.get("authors", [])],
        "published": published.isoformat(),
        "source": "arXiv",
        "source_kind": "preprint",
        "extra": {
            "arxiv_id": arxiv_id,
            "primary_category": item.get("arxiv_primary_category", {}).get(
                "term", category
            ),
            "pdf_url": pdf_url,
            "comment": _clean(item.get("arxiv_comment", "")),
        },
    }


def fetch(since: date) -> list[dict]:
    seen: set[str] = set()
    results: list[dict] = []

    for category in config.ARXIV_CATEGORIES:
        log.info("arXiv: fetching %s since %s", category, since)
        found, status = _fetch_category(category, since)
        oldest = min((e["published"] for e in found), default="none")
        if status == "capped":
            log.warning(
                "arXiv: %s hit the ARXIV_MAX_RESULTS cap of %d before reaching %s "
                "(oldest fetched: %s). Papers from %s to %s were NOT collected — "
                "raise ARXIV_MAX_RESULTS or shorten the lookback window.",
                category, config.ARXIV_MAX_RESULTS, since, oldest, since, oldest,
            )
        elif status == "error":
            log.warning(
                "arXiv: %s stopped on a request failure (oldest fetched: %s); "
                "coverage back to %s is incomplete. Entries missed now will be "
                "picked up next run if they stay inside the lookback window.",
                category, oldest, since,
            )
        for entry in found:
            # A paper cross-listed in two of our categories arrives twice.
            if entry["id"] in seen:
                continue
            # quant-ph is quantum by definition. cs.ET and cond-mat.mes-hall
            # are mostly not, so they earn their place on keywords.
            if category != "quant-ph" and not is_relevant(
                entry["title"], entry["abstract"]
            ):
                continue
            seen.add(entry["id"])
            results.append(entry)
        time.sleep(config.ARXIV_REQUEST_DELAY)

    log.info("arXiv: %d entries", len(results))
    return results
