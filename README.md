# Quantum Computing Research Archive

An agent that collects new quantum computing research and technical writing every
day, summarizes each item with Claude, and publishes a searchable reference site
to GitHub Pages.

Runs entirely in GitHub Actions — nothing to keep running locally.

## How it works

```
sources ──▶ dedupe ──▶ summarize (Claude) ──▶ data/entries.json ──▶ site/ ──▶ Pages
```

1. **Collect.** Each source adapter returns entries for a lookback window
   (7 days by default; the store dedupes, so overlap between runs is harmless).
2. **Dedupe.** By entry id, and by normalized title across sources — so an arXiv
   preprint that later appears as a journal article stays one entry and gains a
   DOI rather than becoming a second card.
3. **Summarize.** Claude writes a 2–3 sentence plain-language summary, a
   "why it matters" line, one to three topic tags from a fixed taxonomy, and a
   technical-depth rating.
4. **Store.** Everything lands in `data/entries.json`, committed to the repo, so
   the archive's growth is visible in git history and the site can be rebuilt
   from scratch without re-hitting any API.
5. **Render.** A static site with client-side search and filtering, monthly
   archive pages, and an RSS feed. No JavaScript dependencies.

## Sources

Everything uses official APIs and publisher feeds — no HTML scraping. arXiv's
rate limit (one request per three seconds) and Crossref's polite-pool
convention are both respected.

| Source | Coverage | Filtering |
|---|---|---|
| **arXiv API** | `quant-ph`, plus `cs.ET` and `cond-mat.mes-hall` | `quant-ph` taken whole; the other two keyword-filtered |
| **Crossref** | Quantum, PRX Quantum, npj QI, QST, EPJ Quantum Technology | None — all quantum-dedicated journals |
| **Feeds** | Nature Quantum Information, AWS Quantum, IonQ, The Quantum Insider, Quantum Computing Report, Phys.org | None for quantum-only feeds |
| **Feeds** | Google Research, Microsoft Research, Quanta | Keyword-filtered |
| **Hacker News** | Algolia search, ≥10 points | Keyword-filtered |

**On vendor blogs:** IBM Quantum, Quantinuum, and Q-CTRL publish no public RSS
feed at any discoverable URL (all candidates 404). Their announcements are
covered indirectly by The Quantum Insider and Quantum Computing Report, both of
which track vendor news closely. If you find a working feed for any of them, add
it to `FEEDS` in `collector/config.py`.

**On the HN threshold:** quantum is a small niche on HN. Measured over 90 days,
a 25-point bar yields ~0.6 stories/week and a 10-point bar ~1.6/week, so the
default is 10. Algolia also matches these queries loosely — a post about
"computing" can rank — so every hit must clear the keyword filter regardless of
score.

## Setup

**This repo must be public.** GitHub Pages cannot publish from a private repo on
a Free plan, and every alternative — a second repo written via deploy key, a
GitHub App token, a PAT — is blocked by `EdenCodeInc` org policy. A single
public repo needs no cross-repo credential at all: Actions publishes to its own
Pages site using the built-in `GITHUB_TOKEN`.

Nothing sensitive lives here. Secrets are held by GitHub, never committed, and
`CONTACT_EMAIL` is deliberately not defaulted in `config.py` for this reason —
it's a repository variable. What is public is the source list, the topic
taxonomy, and the collection history; the content itself is aggregated from
arXiv, Crossref, and public RSS feeds regardless.

### 1. Make the repo public

**Settings → General → Danger Zone → Change repository visibility → Public.**

If that option is greyed out, the org restricts visibility changes and an owner
has to do it. Failing that, create a public repo under your **personal**
account and push there instead — personal repos have none of these
restrictions, and nothing in the code depends on the owner.

### 2. Add the API key

**Settings → Secrets and variables → Actions → Secrets tab → New repository
secret:**

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | your key from [console.anthropic.com](https://console.anthropic.com/settings/keys) |

Optionally, on the **Variables** tab:

| Name | Value | Why |
|---|---|---|
| `CONTACT_EMAIL` | e.g. `you@edencode.ai` | Crossref routes requests carrying a `mailto` to its faster polite pool, and arXiv uses it to reach you if the collector misbehaves. Works without it. |

Secrets and variables are different tabs on the same page and are **not**
interchangeable — the workflow reads `secrets.ANTHROPIC_API_KEY`. An
environment secret (scoped to an Environment) is also invisible to this job; it
must be a repository secret.

No API key yet? Run the workflow with **Skip Claude summarization** ticked. You
get the full archive with original abstracts; entries are marked
`summary_status` so a later pass can fill in summaries without re-collecting.

### 3. Enable Pages

**Settings → Pages → Source: GitHub Actions.** The site lands at
`https://edencodeinc.github.io/research_archive/`.

### 4. Run it

**Actions → Collect and publish → Run workflow.**

The workflow checks every secret and variable up front and names anything
missing, so a misconfiguration fails in seconds rather than after collection.

For the first run, set **Max entries to summarize** higher than the default 120
— a 7-day backfill finds ~300 entries. Or leave it and run three times; the cap
drops the oldest candidates and they're picked up on the next run while they're
still inside the lookback window.

After that it runs daily at 06:15 UTC.

## Running locally

```sh
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

python -m collector.main                 # full run
python -m collector.main --days 30       # wider backfill
python -m collector.main --no-summarize  # skip the API entirely
python -m collector.main --render-only   # rebuild the site from stored data

python -m http.server -d site 8000       # preview at localhost:8000
```

## Cost

Summarization is the only cost. Per entry: roughly 600–900 input tokens (a
system prompt plus one abstract) and ~150 output tokens. Two things keep it
down, both in `collector/summarize.py`:

- **Prompt caching.** The system prompt is byte-identical on every call and
  marked cacheable, so after the first request in each 5-minute window it bills
  at ~10%. The run warms the cache with one sequential call before fanning out —
  concurrent requests can't read a cache entry another request is still writing.
  (The prompt sits close to Claude Opus 5's 512-token cache minimum. If you
  shorten it substantially, caching will silently stop happening — check
  `usage.cache_read_input_tokens` if you're tuning it.)
- **`effort: "low"`.** Summarizing a short abstract against a fixed taxonomy
  isn't an intelligence-sensitive task.

At default settings a daily run of ~30 new entries is a few cents. The first
backfill run is larger. `MAX_NEW_PER_RUN` (default 120) caps how many entries a
single run will summarize so an unexpected flood can't run up an open-ended
bill.

To trade quality for cost, set a `SUMMARY_MODEL` repository variable — but note
abstracts are short, so the absolute saving is small.

## Configuration

Everything tunable lives in `collector/config.py`, and most values can be
overridden by environment variable:

| Variable | Default | Effect |
|---|---|---|
| `LOOKBACK_DAYS` | 7 | how far back each run looks |
| `MAX_NEW_PER_RUN` | 120 | ceiling on entries **summarized** per run. Collection is never capped — overflow is stored unsummarized and drained by later runs. See below. |
| `ARXIV_MAX_RESULTS` | 700 | ceiling on results fetched per arXiv category per run. quant-ph alone runs ~350/week, so this must exceed the volume in your lookback window or the oldest results are dropped. The adapter logs a warning if it hits the cap. |
| `SUMMARY_MODEL` | `claude-opus-5` | model used for summaries |
| `SUMMARY_EFFORT` | `low` | `low` / `medium` / `high` |
| `SUMMARY_CONCURRENCY` | 6 | parallel summarization requests |
| `HN_MIN_POINTS` | 10 | HN score threshold |
| `HOMEPAGE_ENTRIES` | 300 | entries on the front page; older ones go to monthly pages |
| `SITE_TITLE`, `SITE_TAGLINE` | — | site branding |

The **topic taxonomy** is the `TOPICS` list in `config.py`. It is deliberately a
closed vocabulary — free-form tags drift and make the site's topic filter
useless. Editing it changes tagging for *future* entries only; run
`--render-only` after an edit to refresh the filter dropdown.

## The summarization budget

`MAX_NEW_PER_RUN` limits how many entries a single run sends to Claude. It's a
spend circuit-breaker for the pathological case — a wiped store, or broken
dedup, would otherwise try to re-summarize the whole archive in one go.

**It rate-limits, it doesn't discard.** Every collected entry is stored
immediately. Anything over budget is marked `summary_status: "deferred"` and
picked up by a later run, oldest first, before that run's new arrivals. So a
large backfill drains over a few days and converges on its own:

```
day 1: 400 queued -> summarize 120 -> 280 queued
day 2: +40 new    -> summarize 120 -> 200 queued
...
day 5: drained
```

Backlog is always summarized ahead of new entries, so nothing can be starved by
a steady stream of arrivals. Deferred entries appear on the site immediately
with their original abstract and a "Summary queued" note.

`--no-summarize` uses the same mechanism: entries collected that way are simply
deferred, and a later run with credentials fills them in — no re-collection.

**Recorded failures are not retried automatically.** An entry whose summary was
refused or errored keeps that status rather than being re-attempted every run,
since a refusal will refuse again and silently re-billing for it is worse than
leaving it visible. Sweep them up deliberately with `--retry-failed`.

## Adding a source

Drop a module in `collector/sources/` exposing `fetch(since: date) -> list[dict]`
and add it to `ALL_SOURCES` in `collector/sources/__init__.py`. The expected
entry shape is documented at the top of that file. A source that raises is
logged and skipped — one bad day upstream won't cost you the run.

## Troubleshooting

**`no Anthropic credentials found`** — `ANTHROPIC_API_KEY` isn't reaching the
job. In order of likelihood: not added; added on the Variables tab instead of
Secrets; added as an *environment* secret (the `collect` job declares no
environment, so it can't see those); an org-level secret not scoped to this
repo; or a name typo. The preflight step catches all of these before any work
happens.

**`Get Pages site failed` / `Resource not accessible by integration`** on the
deploy job — Pages isn't enabled, or it's set to the wrong source. It must be
**Settings → Pages → Source: GitHub Actions**, not "Deploy from a branch". This
also fails while the repo is still private, since Pages needs a public repo on
a Free plan.

**Site publishes but looks unstyled** — `.nojekyll` is missing from the
uploaded artifact. It's generated by `render.py`; check it's in `site/`.

## Failure behavior

Deliberately degrading rather than fatal, since this runs unattended:

- A source that errors or 404s is logged and skipped.
- HTTP requests retry 3× with backoff on 429 and 5xx.
- If summarization fails for an entry — refusal, rate limit, truncation,
  malformed JSON — the entry is still published with its original abstract and a
  `summary_status` field recording why. An unsummarized entry beats a missing
  one.
- Topics outside the taxonomy are dropped rather than breaking the site filter.
