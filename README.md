# Semantic Scholar MCP Server (merged)

A [FastMCP](https://github.com/jlowin/fastmcp) server for the [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/) — paper search, author info, citation networks, recommendations, **plus BibTeX export, session paper tracking, and author de-duplication**.

This is a **merged fork**: it takes the mature tool surface of one upstream project and grafts on three unique features from another, so you can run a single MCP server instead of two.

## Lineage & attribution

| Role | Upstream | License | What it provides here |
|------|----------|---------|-----------------------|
| **Base fork** | [`zongmin-yu/semantic-scholar-fastmcp-mcp-server`](https://github.com/YUZongmin/semantic-scholar-fastmcp-mcp-server) | MIT © 2025 Zongmin Yu | The 16 core tools, modular package layout, HTTP utilities, rate limiting, HTTP bridge |
| **Ported features** | [`akapet00/semantic-scholar-mcp`](https://github.com/akapet00/semantic-scholar-mcp) | MIT © 2025 Ante Kapetanovic | 5 extra tools: BibTeX export, session paper tracking, author consolidation |

Everything else in this repo (the integration wiring, tests, and fixes) is local work on top of those two. Both upstreams are MIT-licensed, and this fork stays MIT — see [License](#license).

### Why merge instead of running both?

`zongmin-yu` is the more mature server (finer-grained tools: batch lookups up to 1000 IDs, `snippet_search` for in-body excerpts, `paper_autocomplete`). `akapet00` had three things `zongmin-yu` lacked: **BibTeX export**, **session-scoped paper tracking**, and **author record de-duplication**. Rather than install both and juggle two registrations, this fork ports akapet00's three feature areas onto the zongmin-yu base as one server.

## What's new relative to the base fork

**5 new tools** (ported from akapet00, then integrated with the base):

- `export_bibtex` — export papers seen this session (or specific IDs) to BibTeX. Papers with sparse metadata are auto-enriched (re-fetched for DOI/venue/journal/publication type) so entries render as proper `@article`/`@inproceedings` with journal, volume, and pages. Set `enrich=False` to skip network calls.
- `list_tracked_papers` — list papers auto-tracked this session, optionally filtered by which tool retrieved them.
- `clear_tracked_papers` — reset the session tracker.
- `find_duplicate_authors` — surface likely-duplicate author records by shared ORCID/DBLP identifiers.
- `consolidate_authors` — preview/confirm a local merged view of duplicate author records (never modifies Semantic Scholar's data).

**Automatic session tracking:** every paper/author-returning tool (search, details, recommendations, …) records what it returned into a session tracker, so the `search → export_bibtex` flow works with no extra bookkeeping.

**Local fix:** journal papers whose venue string lacks a keyword like "journal"/"letters" (e.g. *Optics Express*, *Physica Scripta*) were being exported as `@misc` with the journal field dropped. `detect_entry_type()` now falls back to `@article` for any named, non-conference venue, and enrichment keys off missing `publicationTypes`/`journal` (which search tools never populate) so the correct type is detected. Verified against the live API.

## Available tools (21 total)

**Papers (8):** `paper_relevance_search`, `paper_bulk_search`, `paper_title_search`, `paper_details`, `paper_batch_details`, `paper_authors`, `paper_autocomplete`, `snippet_search`

**Citations (2):** `paper_citations`, `paper_references`

**Authors (4):** `author_search`, `author_details`, `author_papers`, `author_batch_details`

**Recommendations (2):** `get_paper_recommendations_single`, `get_paper_recommendations_multi`

**BibTeX & tracking (3, new):** `export_bibtex`, `list_tracked_papers`, `clear_tracked_papers`

**Author de-duplication (2, new):** `find_duplicate_authors`, `consolidate_authors`

> All tools follow the official [Semantic Scholar API documentation](https://api.semanticscholar.org/api-docs/) for field specifications.

## Requirements

- Python 3.10+
- A Semantic Scholar API key (optional — unauthenticated access works with lower rate limits)

## Installation & running

This fork is set up for **local use**, run straight from the checkout with [`uv`](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/dosigner/semantic-scholar-mcp-merged.git
cd semantic-scholar-mcp-merged
uv run semantic-scholar-mcp-merged
```

### Register with Claude Code

```json
{
  "mcpServers": {
    "semantic-scholar": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/to/semantic-scholar-mcp-merged",
        "run", "semantic-scholar-mcp-merged"
      ],
      "env": {
        "SEMANTIC_SCHOLAR_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

The `SEMANTIC_SCHOLAR_API_KEY` env var is optional. Get a key from the [Semantic Scholar API](https://www.semanticscholar.org/product/api) for higher rate limits.

## Usage examples

### Search then export to BibTeX

```python
# 1. Search — results are auto-tracked for the session
results = await paper_relevance_search(
    context,
    query="diffractive deep neural network adaptive optics",
    fields=["title", "authors", "year", "venue"],
)

# 2. Export the tracked papers (or specific IDs) to BibTeX
bib = await export_bibtex(
    context,
    paper_ids=["87702d16a3dea4f455df8f9e7e18ff1c99dbd15f"],
    enrich=True,  # re-fetch missing DOI/journal so entries are proper @article
)
```

Produces:

```bibtex
@article{zhan2022,
  title = {Diffractive deep neural network based adaptive optics scheme for vortex beam in oceanic turbulence.},
  author = {Haichao Zhan and Yixiang Peng and Bing Chen and Le Wang and Wennai Wang and Shengmei Zhao},
  year = {2022},
  journal = {Optics express},
  volume = {30 13},
  pages = {23305-23317},
  doi = {10.1364/OE.462241},
  url = {https://doi.org/10.1364/oe.462241},
}
```

### Batch operations

```python
papers = await paper_batch_details(
    context,
    paper_ids=["649def34f8be52c8b66281af98ae884c09aef38b", "ARXIV:2106.15928"],
    fields="title,authors,year,citations",
)
```

## HTTP bridge (optional, off by default)

The base fork ships a small REST bridge (`semantic_scholar.bridge`) exposing endpoints like `GET /v1/paper/search`. It is **disabled by default** in this fork; enable it with:

```bash
SEMANTIC_SCHOLAR_ENABLE_HTTP_BRIDGE=1   # 0 = disabled (default)
SEMANTIC_SCHOLAR_HTTP_BRIDGE_HOST=0.0.0.0
SEMANTIC_SCHOLAR_HTTP_BRIDGE_PORT=8000
```

## Development

```bash
uv run pytest -q -m "not live"   # 176 offline unit tests
```

Tests marked `live` hit the real Semantic Scholar API and are deselected by default.

## Rate limits

- **With API key:** ~1 req/s for search/batch/recommendations, ~10 req/s for others.
- **Without API key:** ~100 requests per 5 minutes, longer timeouts.

Rate limits are subject to change — see the [Semantic Scholar API](https://api.semanticscholar.org/) for current values.

## API terms

This project uses the [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/) from the Allen Institute for AI (AI2). Review the [API License Agreement](https://api.semanticscholar.org/license/) before use.

## License

MIT. This is a derivative work of two MIT-licensed projects; both copyright notices are retained in [`LICENSE`](LICENSE):

- MIT © 2025 Zongmin Yu — base server ([`zongmin-yu/semantic-scholar-fastmcp-mcp-server`](https://github.com/YUZongmin/semantic-scholar-fastmcp-mcp-server))
- MIT © 2025 Ante Kapetanovic — ported BibTeX/tracking/consolidation features ([`akapet00/semantic-scholar-mcp`](https://github.com/akapet00/semantic-scholar-mcp))
