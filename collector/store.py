"""Persistence and deduplication for collected entries.

The store is a single JSON file keyed by entry id. It is committed to the repo,
which makes the archive's history reviewable in git and means the site can be
rebuilt from scratch at any time without re-hitting any API.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Iterable

from . import config

log = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

# An entry that was collected but not yet summarized — either because the
# per-run budget was spent, or because the run used --no-summarize. It is
# stored like any other entry and picked up by a later run.
DEFERRED = "deferred"


def needs_summary(entry: dict) -> bool:
    """True if this entry is waiting for a summary.

    A recorded failure (`refused`, `api_error_500`, ...) is deliberately *not*
    retried automatically: a refusal will refuse again, and silently re-billing
    for it every run is worse than leaving it visible in the data. Use
    --retry-failed to sweep those up.
    """
    status = entry.get("summary_status")
    # None covers entries written before summary_status existed, and by
    # --no-summarize runs; both should be picked up.
    return status in (None, DEFERRED)


def mark_deferred(entry: dict) -> dict:
    """Give an unsummarized entry the fields the templates expect."""
    entry.setdefault("summary", "")
    entry.setdefault("why_it_matters", "")
    entry.setdefault("topics", [])
    entry.setdefault("technical_depth", "overview")
    entry["summary_status"] = DEFERRED
    return entry


def summarization_queue(backlog: list[dict], fresh: list[dict], limit: int) -> list[dict]:
    """Order one run's summarization work, capped at `limit`.

    Backlog first, oldest first, so a deferred entry can never be starved
    indefinitely by a steady stream of new arrivals. New entries follow,
    newest first, so the front page stays current when the budget is tight.
    """
    ordered_backlog = sorted(
        backlog, key=lambda e: (e.get("published", ""), e.get("id", ""))
    )
    ordered_fresh = sorted(
        fresh, key=lambda e: (e.get("published", ""), e.get("id", "")), reverse=True
    )
    return (ordered_backlog + ordered_fresh)[:limit]


def title_key(title: str) -> str:
    """Normalized title used to catch the same work arriving twice under
    different ids — most often an arXiv preprint that later appears as a
    journal article with a DOI."""
    return _NON_ALNUM.sub(" ", (title or "").lower()).strip()


def load() -> dict[str, dict]:
    if not config.STORE_PATH.exists():
        return {}
    with config.STORE_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return {entry["id"]: entry for entry in data.get("entries", [])}


def save(entries: dict[str, dict]) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        entries.values(), key=lambda e: (e.get("published", ""), e.get("id", "")), reverse=True
    )
    payload = {"count": len(ordered), "entries": ordered}
    with config.STORE_PATH.open("w", encoding="utf-8") as fh:
        # sort_keys keeps the committed file's diff minimal between runs.
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
    log.info("store: wrote %d entries to %s", len(ordered), config.STORE_PATH)


def select_new(existing: dict[str, dict], candidates: Iterable[dict]) -> list[dict]:
    """Return the candidates that are genuinely new.

    Existing entries are enriched in place when a duplicate carries information
    the stored copy lacks (a DOI for a paper first seen as a preprint, say).
    """
    by_title = {title_key(e["title"]): e for e in existing.values() if e.get("title")}
    fresh: list[dict] = []
    seen_this_run: set[str] = set()

    for candidate in candidates:
        cid = candidate["id"]
        if cid in existing or cid in seen_this_run:
            continue

        key = title_key(candidate["title"])
        prior = by_title.get(key) if key else None
        if prior is not None:
            _merge(prior, candidate)
            continue

        seen_this_run.add(cid)
        if key:
            by_title[key] = candidate
        fresh.append(candidate)

    return fresh


def _merge(prior: dict, duplicate: dict) -> None:
    """Fold a duplicate's extra information into the entry we already have."""
    prior.setdefault("also_at", [])
    reference = {
        "source": duplicate.get("source", ""),
        "url": duplicate.get("url", ""),
        "published": duplicate.get("published", ""),
    }
    if reference["url"] and reference["url"] not in [
        r.get("url") for r in prior["also_at"]
    ]:
        prior["also_at"].append(reference)

    # A DOI is the one field worth promoting onto the primary record: it turns a
    # preprint entry into a citable one.
    doi = (duplicate.get("extra") or {}).get("doi")
    if doi and not (prior.get("extra") or {}).get("doi"):
        prior.setdefault("extra", {})["doi"] = doi

    # Prefer a real abstract over an empty one.
    if not prior.get("abstract") and duplicate.get("abstract"):
        prior["abstract"] = duplicate["abstract"]
