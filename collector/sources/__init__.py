"""Source adapters. Each exposes `fetch(since) -> list[dict]` of raw entries.

Every adapter returns dicts with the same shape so the rest of the pipeline
doesn't care where an entry came from:

    {
        "id":         stable unique string (used for dedup),
        "title":      str,
        "url":        str,
        "abstract":   str,          # may be empty for link-only sources
        "authors":    list[str],
        "published":  ISO-8601 date string (YYYY-MM-DD),
        "source":     human-readable source name,
        "source_kind": one of "preprint" | "journal" | "blog" | "news",
        "extra":      dict of source-specific fields (doi, hn_points, ...)
    }
"""

from . import arxiv, crossref, feeds, hackernews

ALL_SOURCES = [arxiv, crossref, feeds, hackernews]

__all__ = ["arxiv", "crossref", "feeds", "hackernews", "ALL_SOURCES"]
