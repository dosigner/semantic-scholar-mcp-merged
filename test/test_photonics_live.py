"""Live regression guard for the photonics venue registry.

Every verified venue string must still return >0 hits when used as a filter.
If Semantic Scholar renames a venue, this catches it. Excluded from the
default run (`-m "not live"`); run explicitly:

    uv run pytest -q -m live test/test_photonics_live.py

Runs as a single paced test (not parametrized) so the ~20 requests stay under
the unauthenticated rate limit (~1 req/s); firing them all at once trips 429s
and the transport's retries then compound the overage.
"""

import asyncio

import pytest

from semantic_scholar.api.photonics import PHOTONICS_SOURCES
from semantic_scholar.utils.http import make_request

pytestmark = [pytest.mark.live, pytest.mark.asyncio]

_PACE_SECONDS = 1.3


async def _venue_total(venue: str) -> int:
    """Return the filtered result count, retrying transient API/rate-limit
    errors so a stray 429 doesn't masquerade as a renamed venue (0 hits)."""
    for attempt in range(4):
        resp = await make_request(
            "/paper/search/bulk",
            params={
                "venue": venue,
                "fields": "venue",
                "publicationDateOrYear": "2015:",
            },
        )
        if isinstance(resp, dict) and "error" not in resp:
            return resp.get("total", 0) or 0
        await asyncio.sleep(_PACE_SECONDS * (attempt + 2))  # backoff on error
    return -1  # persistent API error / rate limit


async def test_all_venue_strings_still_filter():
    all_venues = [v for src in PHOTONICS_SOURCES.values() for v in src.venues]
    failures: list[tuple[str, int]] = []
    for venue in all_venues:
        total = await _venue_total(venue)
        if total <= 0:
            failures.append((venue, total))
        await asyncio.sleep(_PACE_SECONDS)

    assert not failures, (
        "venue strings that no longer filter (total<=0; -1 means API error): "
        + ", ".join(f"{v!r}={t}" for v, t in failures)
    )
