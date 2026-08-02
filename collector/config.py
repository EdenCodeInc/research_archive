"""Central configuration: sources, filters, and tuning knobs."""

from __future__ import annotations

import os
from pathlib import Path

# --- Paths -------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STORE_PATH = DATA_DIR / "entries.json"
SITE_DIR = ROOT / "site"
TEMPLATE_DIR = ROOT / "collector" / "templates"

# --- Site identity -----------------------------------------------------------

SITE_TITLE = os.environ.get("SITE_TITLE", "Quantum Computing Research Archive")
SITE_TAGLINE = os.environ.get(
    "SITE_TAGLINE",
    "Automatically collected papers, preprints, and technical writing on quantum computing.",
)

# Contact address sent to arXiv and Crossref so they can reach us if our
# requests misbehave. Crossref routes requests with a mailto to its faster
# "polite pool", so this is worth setting properly.
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "pranav@edencode.ai")
USER_AGENT = f"quantum-research-archive/1.0 (mailto:{CONTACT_EMAIL})"

# --- Collection window -------------------------------------------------------

# How far back each run looks. The store dedupes, so overlapping windows across
# runs are harmless — this only needs to exceed the gap between runs.
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))

# Hard ceiling on how many new entries a single run will summarize, so an
# unexpected flood of results can't run up an unbounded API bill.
MAX_NEW_PER_RUN = int(os.environ.get("MAX_NEW_PER_RUN", "120"))

# --- arXiv -------------------------------------------------------------------

# quant-ph is the primary quantum category. cs.ET (emerging technologies) and
# cond-mat.mes-hall (mesoscopic physics, where much hardware work lands) catch
# relevant work that is cross-listed rather than primary.
ARXIV_CATEGORIES = ["quant-ph", "cs.ET", "cond-mat.mes-hall"]
ARXIV_MAX_RESULTS = int(os.environ.get("ARXIV_MAX_RESULTS", "150"))
# arXiv asks for no more than one request every three seconds.
ARXIV_REQUEST_DELAY = 3.0

# --- Crossref ----------------------------------------------------------------

# Journals dedicated to quantum information — everything they publish is
# on-topic, so these are taken unfiltered.
CROSSREF_ISSNS = {
    "2521-327X": "Quantum",
    "2691-3399": "PRX Quantum",
    "2056-6387": "npj Quantum Information",
    "2058-9565": "Quantum Science and Technology",
    "2364-9061": "EPJ Quantum Technology",
}
CROSSREF_ROWS = 100

# --- Vendor / lab / news feeds -----------------------------------------------

# (name, url, needs_keyword_filter)
# Feeds marked True publish broadly, so entries are keyword-filtered for
# quantum relevance. Feeds marked False are quantum-only and taken whole.
#
# IBM Quantum, Quantinuum, and Q-CTRL publish no public RSS — their
# announcements are picked up via The Quantum Insider and Quantum Computing
# Report, both of which cover vendor news closely. See the README before
# adding a feed.
FEEDS = [
    ("Nature: Quantum Information", "https://www.nature.com/subjects/quantum-information.rss", False),
    ("AWS Quantum Computing", "https://aws.amazon.com/blogs/quantum-computing/feed/", False),
    ("IonQ", "https://ionq.com/blog/rss.xml", False),
    ("The Quantum Insider", "https://thequantuminsider.com/feed/", False),
    ("Quantum Computing Report", "https://quantumcomputingreport.com/feed/", False),
    ("Phys.org Quantum Physics", "https://phys.org/rss-feed/physics-news/quantum-physics/", False),
    ("Google Research", "https://research.google/blog/rss/", True),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/", True),
    ("Quanta Magazine", "https://api.quantamagazine.org/feed/", True),
]

# --- Hacker News -------------------------------------------------------------

HN_QUERIES = ["quantum computing", "quantum error correction", "qubit"]
# Calibrated against 90 days of HN history: quantum is a small niche there, so
# a 25-point bar yields ~0.6 stories/week and a 10-point bar ~1.6/week. Algolia
# also matches these queries loosely (a post about "computing" can rank), so
# every hit still has to clear the keyword filter regardless of score.
HN_MIN_POINTS = int(os.environ.get("HN_MIN_POINTS", "10"))

# --- Relevance filtering -----------------------------------------------------

# Applied to broad-spectrum sources only (general blogs, HN, Quanta). Dedicated
# quantum sources bypass this entirely.
QUANTUM_KEYWORDS = [
    "quantum",
    "qubit",
    "qutrit",
    "qudit",
    "superconducting circuit",
    "trapped ion",
    "photonic computing",
    "topological qubit",
    "error correction",
    "annealing",
    "qiskit",
    "cirq",
]

# Terms that look quantum but usually are not, in a computing context.
NEGATIVE_KEYWORDS = [
    "quantum leap",
    "quantum of solace",
]

# --- Summarization -----------------------------------------------------------

# Default to the most capable model. Abstracts are short, so per-item cost is
# small; override via env var if you want to trade quality for spend.
SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "claude-opus-5")
SUMMARY_EFFORT = os.environ.get("SUMMARY_EFFORT", "low")
SUMMARY_CONCURRENCY = int(os.environ.get("SUMMARY_CONCURRENCY", "6"))

# The controlled vocabulary the model tags each entry against. Keeping this
# fixed is what makes the site's topic filter useful — free-form tags drift.
TOPICS = [
    "Error correction & fault tolerance",
    "Hardware: superconducting",
    "Hardware: trapped ion",
    "Hardware: photonic",
    "Hardware: neutral atom",
    "Hardware: spin & topological",
    "Algorithms & complexity",
    "Quantum simulation & chemistry",
    "Quantum machine learning",
    "Cryptography & post-quantum",
    "Networking & communication",
    "Control, calibration & benchmarking",
    "Software & tooling",
    "Industry, funding & policy",
]

# --- Rendering ---------------------------------------------------------------

# Entries shown on the front page. Older ones live on monthly archive pages.
HOMEPAGE_ENTRIES = int(os.environ.get("HOMEPAGE_ENTRIES", "300"))
