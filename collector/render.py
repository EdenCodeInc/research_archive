"""Static site generation.

Produces a self-contained `site/` directory: a front page with client-side
search and filtering, one page per month of archive, and an RSS feed. No build
step, no JavaScript dependencies — it can be served by GitHub Pages as-is.
"""

from __future__ import annotations

import logging
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import config

log = logging.getLogger(__name__)


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(config.TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _author_line(entry: dict) -> str:
    authors = entry.get("authors") or []
    if not authors:
        return ""
    if len(authors) <= 3:
        return ", ".join(authors)
    return f"{authors[0]} et al."


def _prepare(entry: dict) -> dict:
    """Add the derived fields the templates need, without mutating the store."""
    view = dict(entry)
    view.setdefault("topics", [])
    view.setdefault("extra", {})
    view["author_line"] = _author_line(entry)

    # Lowercased haystack for the client-side search box. Kept on a data
    # attribute so filtering needs no index and no fetch.
    view["search_text"] = " ".join(
        [
            entry.get("title", ""),
            entry.get("summary", ""),
            entry.get("why_it_matters", ""),
            entry.get("source", ""),
            " ".join(entry.get("authors") or []),
            " ".join(entry.get("topics") or []),
        ]
    ).lower()

    try:
        published = datetime.strptime(entry["published"], "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    except (KeyError, ValueError):
        published = datetime.now(timezone.utc)
    view["rfc822"] = format_datetime(published)
    view["month_slug"] = published.strftime("%Y-%m")
    view["month_label"] = published.strftime("%B %Y")

    summary = entry.get("summary") or entry.get("abstract") or ""
    matters = entry.get("why_it_matters") or ""
    view["feed_description"] = f"{summary} {matters}".strip()[:1200]
    return view


def build(entries: list[dict], site_url: str = "") -> None:
    env = _env()
    views = [_prepare(e) for e in entries]
    views.sort(key=lambda v: (v.get("published", ""), v.get("id", "")), reverse=True)

    by_month: dict[str, list[dict]] = defaultdict(list)
    for view in views:
        by_month[view["month_slug"]].append(view)

    months = [
        {
            "slug": slug,
            "label": items[0]["month_label"],
            "count": len(items),
        }
        for slug, items in sorted(by_month.items(), reverse=True)
    ]

    sources = sorted({v["source"] for v in views if v.get("source")})
    generated_at = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    if config.SITE_DIR.exists():
        shutil.rmtree(config.SITE_DIR)
    (config.SITE_DIR / "archive").mkdir(parents=True, exist_ok=True)

    common = {
        "site_title": config.SITE_TITLE,
        "tagline": config.SITE_TAGLINE,
        "topics": config.TOPICS,
        "sources": sources,
        "total_count": len(views),
        "generated_at": generated_at,
        "months": months,
    }

    page = env.get_template("page.html")

    # Front page: the most recent slice, so the page stays fast as the archive
    # grows into the thousands. Everything older is reachable by month.
    recent = views[: config.HOMEPAGE_ENTRIES]
    (config.SITE_DIR / "index.html").write_text(
        page.render(
            **common,
            page_title=config.SITE_TITLE,
            heading=(
                f"Latest {len(recent)} entries" if len(views) > len(recent) else None
            ),
            entries=recent,
            root="",
        ),
        encoding="utf-8",
    )

    for slug, items in by_month.items():
        (config.SITE_DIR / "archive" / f"{slug}.html").write_text(
            page.render(
                **common,
                page_title=f"{items[0]['month_label']} — {config.SITE_TITLE}",
                heading=items[0]["month_label"],
                entries=items,
                root="../",
            ),
            encoding="utf-8",
        )

    feed = env.get_template("feed.xml")
    (config.SITE_DIR / "feed.xml").write_text(
        feed.render(
            site_title=config.SITE_TITLE,
            tagline=config.SITE_TAGLINE,
            site_url=site_url.rstrip("/"),
            build_date=format_datetime(datetime.now(timezone.utc)),
            entries=views[:100],
        ),
        encoding="utf-8",
    )

    # Tell GitHub Pages not to run the output through Jekyll, which would
    # otherwise ignore any file or directory starting with an underscore.
    (config.SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")

    log.info(
        "render: %d entries -> %s (%d monthly pages)",
        len(views),
        config.SITE_DIR,
        len(months),
    )
