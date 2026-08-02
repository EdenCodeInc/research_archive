"""Hacker News stories via the Algolia search API.

https://hn.algolia.com/api

The noisiest source by a wide margin, so it is gated on both a keyword match
and a points threshold — the community upvote acts as a crude quality filter.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone

from .. import config
from ..http import get
from ..relevance import is_relevant

log = logging.getLogger(__name__)

API_URL = "https://hn.algolia.com/api/v1/search_by_date"


def _fetch_query(query: str, since: date) -> list[dict]:
    cutoff = int(datetime.combine(since, time.min, tzinfo=timezone.utc).timestamp())
    params = {
        "query": query,
        "tags": "story",
        "numericFilters": f"created_at_i>{cutoff},points>={config.HN_MIN_POINTS}",
        "hitsPerPage": 50,
    }
    response = get(API_URL, params=params)
    if response is None:
        return []

    try:
        hits = response.json()["hits"]
    except (ValueError, KeyError) as exc:
        log.warning("HN: unexpected response for %r (%s)", query, exc)
        return []

    entries = []
    for hit in hits:
        title = (hit.get("title") or "").strip()
        if not title or not is_relevant(title, hit.get("story_text") or ""):
            continue

        object_id = hit.get("objectID", "")
        discussion = f"https://news.ycombinator.com/item?id={object_id}"
        # Self-posts have no external URL; point those at the discussion.
        url = hit.get("url") or discussion

        created = hit.get("created_at", "")[:10]
        if not created:
            continue

        entries.append(
            {
                "id": f"hn:{object_id}",
                "title": title,
                "url": url,
                "abstract": (hit.get("story_text") or "").strip()[:2000],
                "authors": [],
                "published": created,
                "source": "Hacker News",
                "source_kind": "news",
                "extra": {
                    "points": hit.get("points", 0),
                    "comments": hit.get("num_comments", 0),
                    "discussion_url": discussion,
                },
            }
        )
    return entries


def fetch(since: date) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()

    for query in config.HN_QUERIES:
        log.info("HN: searching %r", query)
        for entry in _fetch_query(query, since):
            if entry["id"] in seen:
                continue
            seen.add(entry["id"])
            results.append(entry)

    log.info("Hacker News: %d entries", len(results))
    return results
