"""Entry point: collect -> dedupe -> summarize -> store -> render.

    python -m collector.main                 # full run
    python -m collector.main --no-summarize  # skip the API calls
    python -m collector.main --render-only   # rebuild the site from the store
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from . import config, render, store, summarize
from .sources import ALL_SOURCES

log = logging.getLogger("collector")


def _have_credentials() -> bool:
    """True if the Anthropic SDK will find a credential.

    Mirrors the SDK's own resolution order: the two environment variables, then
    a profile written by `ant auth login`. Checking the profile directory too
    keeps local runs from being told to set an env var they don't need.
    """
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True

    config_dir = os.environ.get("ANTHROPIC_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".config" / "anthropic"
    credentials = base / "credentials"
    return credentials.is_dir() and any(credentials.glob("*.json"))


def collect(since: date) -> list[dict]:
    collected: list[dict] = []
    for module in ALL_SOURCES:
        name = module.__name__.rsplit(".", 1)[-1]
        try:
            collected.extend(module.fetch(since))
        except Exception:
            # One source having a bad day should not cost us the whole run.
            log.exception("source %s failed; continuing without it", name)
    return collected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect and publish quantum computing research.")
    parser.add_argument(
        "--days", type=int, default=config.LOOKBACK_DAYS, help="how far back to look"
    )
    parser.add_argument(
        "--no-summarize", action="store_true", help="skip Claude API calls"
    )
    parser.add_argument(
        "--render-only", action="store_true", help="rebuild the site from the stored data"
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="also re-attempt entries whose summary previously errored or was refused",
    )
    parser.add_argument(
        "--site-url", default=os.environ.get("SITE_URL", ""), help="public URL, used in the RSS feed"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )

    # Check credentials before doing any work. Collection takes ~30s of polite,
    # rate-limited requests to arXiv and Crossref; there is no reason to spend
    # that only to fail on a missing key at the end.
    needs_api = not args.render_only and not args.no_summarize
    if needs_api and not _have_credentials():
        log.error(
            "no Anthropic credentials found. Set ANTHROPIC_API_KEY, or run with "
            "--no-summarize to publish raw abstracts instead."
        )
        return 1

    entries = store.load()
    log.info("store: loaded %d existing entries", len(entries))

    if not args.render_only:
        since = date.today() - timedelta(days=args.days)
        candidates = collect(since)
        log.info("collected %d candidate entries since %s", len(candidates), since)

        fresh = store.select_new(entries, candidates)
        log.info("%d are new after deduplication", len(fresh))

        # Everything collected is stored immediately, summarized or not. The
        # budget below rate-limits summarization; it never discards an entry.
        backlog = [e for e in entries.values() if store.needs_summary(e)]
        if args.retry_failed:
            retryable = [
                e
                for e in entries.values()
                if not store.needs_summary(e) and e.get("summary_status") != "ok"
            ]
            log.info("retrying %d previously failed summaries", len(retryable))
            backlog += retryable

        for entry in fresh:
            store.mark_deferred(entry)
            entries[entry["id"]] = entry

        if args.no_summarize:
            log.info(
                "skipping summarization; %d entries are queued for a later run",
                len(backlog) + len(fresh),
            )
        else:
            queue = store.summarization_queue(backlog, fresh, config.MAX_NEW_PER_RUN)
            waiting = len(backlog) + len(fresh) - len(queue)
            fresh_ids = {e["id"] for e in fresh}
            from_new = sum(1 for e in queue if e["id"] in fresh_ids)
            log.info(
                "summarizing %d this run (%d from backlog, %d new)",
                len(queue),
                len(queue) - from_new,
                from_new,
            )
            if waiting:
                log.warning(
                    "%d entries exceed the MAX_NEW_PER_RUN budget of %d. They are "
                    "stored and will be summarized by a later run — nothing is "
                    "lost. Raise MAX_NEW_PER_RUN to clear them sooner.",
                    waiting,
                    config.MAX_NEW_PER_RUN,
                )
            if queue:
                summarize.summarize_all(queue)

        store.save(entries)

    render.build(list(entries.values()), site_url=args.site_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
