"""Keyword relevance check for broad-spectrum sources.

Dedicated quantum sources (quant-ph, PRX Quantum, the vendor quantum blogs)
bypass this — everything they publish is on topic. It exists to keep general
feeds like Microsoft Research or Hacker News from flooding the archive with
unrelated posts.
"""

from __future__ import annotations

from . import config

_KEYWORDS = [k.lower() for k in config.QUANTUM_KEYWORDS]
_NEGATIVE = [k.lower() for k in config.NEGATIVE_KEYWORDS]


def is_relevant(*texts: str) -> bool:
    haystack = " ".join(t for t in texts if t).lower()
    if not haystack:
        return False
    if any(neg in haystack for neg in _NEGATIVE):
        return False
    return any(kw in haystack for kw in _KEYWORDS)
