"""Plain-language summaries and topic tags via the Claude Messages API.

Two things keep the cost down without hurting quality:

* **Prompt caching.** The system prompt (instructions plus the topic taxonomy)
  is identical on every request, so it is marked cacheable and billed at ~10%
  after the first call in each 5-minute window.
* **Low effort.** Summarizing a short abstract against a fixed taxonomy is not
  an intelligence-sensitive task, so `effort: "low"` cuts token spend with no
  measurable quality loss here.

Both are tunable in config.py.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import anthropic

from . import config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = f"""\
You write short, factual entries for an internal reference site that an \
engineering team uses to keep up with quantum computing research. Your readers \
are strong software engineers with an undergraduate physics background. They \
are not specialists in quantum information, but they do not need concepts \
defined from scratch.

For each item you are given a title, a source, and (usually) an abstract or \
excerpt. Produce:

1. `summary` — two or three sentences, plain language, describing what the work \
actually does or reports. Lead with the result, not the motivation. Name the \
concrete artifact where there is one: the qubit count, the error rate, the \
algorithm, the hardware platform. Do not open with "This paper" or "The \
authors". Do not editorialize about how important or exciting it is.

2. `why_it_matters` — one sentence on the practical consequence for someone \
building on or tracking this area. If the work is incremental, say so plainly \
rather than inflating it.

3. `topics` — one to three labels drawn *only* from the controlled vocabulary \
below. Use the exact strings. Choose the most specific labels that genuinely \
apply; do not pad the list to reach three.

4. `technical_depth` — one of "overview", "applied", or "theoretical". Use \
"overview" for news, announcements, and explainers; "applied" for experimental \
results, hardware, benchmarks, and tooling; "theoretical" for proofs, \
complexity results, and formal analysis.

Controlled vocabulary for `topics`:
{chr(10).join('- ' + t for t in config.TOPICS)}

Ground every claim in the text you are given. If the abstract is missing or too \
thin to summarize, say what the item appears to be based on its title and \
source, and keep it short — do not invent findings, numbers, or conclusions.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string", "enum": config.TOPICS}},
        "technical_depth": {
            "type": "string",
            "enum": ["overview", "applied", "theoretical"],
        },
    },
    "required": ["summary", "why_it_matters", "topics", "technical_depth"],
    "additionalProperties": False,
}


def _build_prompt(entry: dict) -> str:
    authors = ", ".join(entry.get("authors", [])[:8])
    if len(entry.get("authors", [])) > 8:
        authors += ", et al."

    abstract = (entry.get("abstract") or "").strip()
    parts = [
        f"Title: {entry['title']}",
        f"Source: {entry.get('source', 'unknown')} ({entry.get('source_kind', 'unknown')})",
        f"Published: {entry.get('published', 'unknown')}",
    ]
    if authors:
        parts.append(f"Authors: {authors}")
    parts.append("")
    parts.append(
        f"Abstract / excerpt:\n{abstract}" if abstract else "Abstract / excerpt: (none available)"
    )
    return "\n".join(parts)


def _fallback(entry: dict, reason: str) -> dict:
    """Used when the API declines or errors. The entry still lands on the site
    with its original abstract — an unsummarized entry beats a missing one."""
    log.warning("summary unavailable for %s: %s", entry["id"], reason)
    return {
        "summary": "",
        "why_it_matters": "",
        "topics": [],
        "technical_depth": "overview",
        "summary_status": reason,
    }


def _summarize_one(client: anthropic.Anthropic, entry: dict) -> dict:
    try:
        response = client.messages.create(
            model=config.SUMMARY_MODEL,
            max_tokens=2000,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    # Identical on every call in the run, so cache it once and
                    # read it back for the rest of the batch.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            output_config={
                "effort": config.SUMMARY_EFFORT,
                "format": {"type": "json_schema", "schema": RESPONSE_SCHEMA},
            },
            messages=[{"role": "user", "content": _build_prompt(entry)}],
        )
    except anthropic.RateLimitError as exc:
        # The SDK already retried with backoff; if we are still limited, skip.
        return _fallback(entry, f"rate_limited: {exc}")
    except anthropic.APIStatusError as exc:
        return _fallback(entry, f"api_error_{exc.status_code}")
    except anthropic.APIConnectionError as exc:
        return _fallback(entry, f"connection_error: {exc}")

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        return _fallback(entry, f"refused: {category}")
    if response.stop_reason == "max_tokens":
        return _fallback(entry, "truncated")

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _fallback(entry, "unparseable_response")

    parsed["summary_status"] = "ok"
    # Guard against a topic slipping outside the taxonomy; the site's filter
    # is built from config.TOPICS and would silently drop anything else.
    parsed["topics"] = [t for t in parsed.get("topics", []) if t in config.TOPICS]
    return parsed


def summarize_all(entries: list[dict]) -> None:
    """Attach summary fields to each entry, in place."""
    if not entries:
        return

    client = anthropic.Anthropic()

    # Warm the prompt cache with a single call before fanning out. Concurrent
    # requests cannot read a cache entry another request is still writing, so
    # without this the whole first wave pays full price for the system prompt.
    log.info("summarizing %d entries with %s", len(entries), config.SUMMARY_MODEL)
    entries[0].update(_summarize_one(client, entries[0]))

    remaining = entries[1:]
    if remaining:
        with ThreadPoolExecutor(max_workers=config.SUMMARY_CONCURRENCY) as pool:
            results = pool.map(lambda e: _summarize_one(client, e), remaining)
            for entry, result in zip(remaining, results):
                entry.update(result)

    ok = sum(1 for e in entries if e.get("summary_status") == "ok")
    log.info("summarized %d/%d entries successfully", ok, len(entries))
