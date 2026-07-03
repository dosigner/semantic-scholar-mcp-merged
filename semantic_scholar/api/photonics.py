"""Photonics venue-preset search tools.

These wrap the existing Semantic Scholar search endpoints with a curated
registry of exact `venue` filter strings for four photonics publishers the
user follows: Optica Publishing Group, SPIE, Light: Science & Applications,
and Nature Photonics. None of those sites expose a public search API, but S2
indexes all of them and its search tools already accept a `venue` OR-filter.

The venue strings below are VERIFIED, not guessed — every string was round-trip
tested by `scripts/verify_photonics_venues.py` against the live API (each
returns >0 hits and the returned `venue` matches). Re-run that script and
`test/test_photonics_live.py` if S2 renames a venue.

Two S2 quirks the registry already accounts for:
  * Individual papers often have an empty `venue` field even though the filter
    works — so strings are validated by round-trip filtering, not lookup.
  * The literal '&' in "Light: Science & Applications" breaks the query string;
    S2 normalizes "and" -> "&", so the filter string uses the "and" spelling.
  * The venue filter is comma-joined (core/requests.py), so a venue string
    containing a comma is inexpressible. None of the verified strings contain a
    comma; any that would are recorded in KNOWN_UNFILTERABLE for transparency.
"""

import datetime
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from fastmcp import Context

from ..config import ErrorType
from ..core.client import S2Client, make_compat_client
from ..core.exceptions import S2Error, S2ValidationError
from ..core.requests import PaperBulkSearchRequest, PaperRelevanceSearchRequest
from ..mcp import mcp
from ..tracking_hook import track_papers
from ..utils.errors import create_error_response, s2_exception_to_error_response
from ..utils.http import make_request


@dataclass(frozen=True)
class PhotonicsSource:
    """A publisher preset: a label plus the exact S2 venue strings it covers."""

    key: str
    label: str
    homepage: str
    venues: Tuple[str, ...]
    note: str = ""


# Verified against the live API by scripts/verify_photonics_venues.py.
PHOTONICS_SOURCES: Dict[str, PhotonicsSource] = {
    "optica": PhotonicsSource(
        key="optica",
        label="Optica Publishing Group",
        homepage="https://opg.optica.org/",
        venues=(
            "Optics Express",
            "Optics Letters",
            "Optica",
            "Applied Optics",
            "Photonics Research",
            "Optics Continuum",
            "Biomedical Optics Express",
            "Optical Materials Express",
            "Advances in Optics and Photonics",
            "Journal of the Optical Society of America A",
            "Journal of the Optical Society of America B",
        ),
    ),
    "spie": PhotonicsSource(
        key="spie",
        label="SPIE Digital Library",
        homepage="https://www.spiedigitallibrary.org/",
        venues=(
            # SPIE journals (durable, reliably filterable).
            "Advanced Photonics",
            "Optical Engineering",  # S2 normalizes to "Optical Engineering: The Journal of SPIE"
            "Neurophotonics",
            "Journal of Biomedical Optics",
            # A few large photonics-relevant SPIE conference proceedings that
            # verified. SPIE proceedings are indexed PER-CONFERENCE in S2, so
            # this is NOT comprehensive coverage of Proceedings of SPIE.
            "SPIE/COS Photonics Asia",
            "Defense + Commercial Sensing",
            "Optical Engineering + Applications",
        ),
        note=(
            "SPIE conference proceedings are indexed per-conference in Semantic "
            "Scholar; only the SPIE journals plus a few major proceedings are "
            "covered. For a specific SPIE conference, pass its venue name to "
            "paper_relevance_search directly."
        ),
    ),
    "nature_lsa": PhotonicsSource(
        key="nature_lsa",
        label="Light: Science & Applications (Nature)",
        homepage="https://www.nature.com/lsa/",
        # "and" spelling — S2 normalizes it to the stored "&" form; the literal
        # "&" would break the query string.
        venues=("Light: Science and Applications",),
    ),
    "nature_photonics": PhotonicsSource(
        key="nature_photonics",
        label="Nature Photonics",
        homepage="https://www.nature.com/nphoton/",
        venues=("Nature Photonics",),
    ),
}

# Venue strings that cannot be expressed in the comma-joined filter (contain a
# comma). Currently none — every verified string is comma-free. Kept as an
# explicit, surfaced record so coverage gaps are never silent.
KNOWN_UNFILTERABLE: Dict[str, List[str]] = {}

# Default response fields for search_photonics (relevance search — you want the
# abstract to judge relevance). All are in PaperFields.VALID_FIELDS. Including
# externalIds/venue makes downstream export_bibtex enrichment cheaper.
_DEFAULT_FIELDS: List[str] = [
    "title",
    "abstract",
    "year",
    "citationCount",
    "authors",
    "url",
    "venue",
    "publicationDate",
    "externalIds",
]

# Leaner default for recent_photonics: it's a monitoring firehose that can return
# hundreds of papers with no query, so abstracts are omitted by default to keep
# the payload scannable and avoid blowing the response-size limit. Pass an
# explicit `fields` list (add "abstract") when you want fuller records.
_RECENT_FIELDS: List[str] = [
    "title",
    "year",
    "citationCount",
    "authors",
    "url",
    "venue",
    "publicationDate",
    "externalIds",
]


def _client() -> S2Client:
    return make_compat_client(make_request)


def resolve_photonics_venues(
    sources: Optional[List[str]],
) -> Tuple[List[str], List[str]]:
    """Resolve preset source keys to (resolved_keys, merged_deduped_venues).

    sources=None -> all four sources. An unknown key raises S2ValidationError
    with the valid keys in details (mirrors the existing validation style).
    """
    if sources is None:
        keys = list(PHOTONICS_SOURCES.keys())
    else:
        unknown = [s for s in sources if s not in PHOTONICS_SOURCES]
        if unknown:
            raise S2ValidationError(
                message=f"Unknown photonics source(s): {', '.join(unknown)}",
                details={"valid_sources": list(PHOTONICS_SOURCES.keys())},
                field="sources",
            )
        keys = list(dict.fromkeys(sources))  # dedupe, preserve order

    merged: List[str] = []
    for key in keys:
        for venue in PHOTONICS_SOURCES[key].venues:
            if venue not in merged:
                merged.append(venue)
    return keys, merged


def date_range_from_days(
    days: int, today: Optional[datetime.date] = None
) -> str:
    """days=30 -> '<today-30>:' open-ended range for publicationDateOrYear.

    `today` is injectable for deterministic tests. days must be >= 1.
    """
    if days < 1:
        raise S2ValidationError(
            message="days must be a positive integer", field="days"
        )
    ref = today or datetime.date.today()
    start = ref - datetime.timedelta(days=days)
    return f"{start.isoformat()}:"


@mcp.tool()
async def search_photonics(
    context: Context,
    query: str,
    sources: Optional[List[str]] = None,
    year: Optional[str] = None,
    min_citation_count: Optional[int] = None,
    fields: Optional[List[str]] = None,
    open_access_pdf: bool = False,
    offset: int = 0,
    limit: int = 20,
) -> Dict:
    """Relevance search restricted to the four photonics publishers
    (Optica, SPIE, Light: Science & Applications, Nature Photonics).

    `sources` is a subset of ["optica","spie","nature_lsa","nature_photonics"];
    None means all four. Results are auto-tracked, so export_bibtex works on
    them without extra steps. Use list_photonics_sources to see coverage.
    """
    try:
        resolved_keys, venues = resolve_photonics_venues(sources)
        request = PaperRelevanceSearchRequest(
            query=query,
            fields=fields or list(_DEFAULT_FIELDS),
            open_access_pdf=open_access_pdf,
            min_citation_count=min_citation_count,
            year=year,
            venue=venues,
            offset=offset,
            limit=limit,
        )
        result = await _client().search_papers(request)
        track_papers(result, "search_photonics")
        if isinstance(result, dict) and "error" not in result:
            result = {"sources": resolved_keys, "venue_filter": venues, **result}
        return result
    except S2ValidationError as exc:
        return s2_exception_to_error_response(exc)
    except S2Error as exc:
        return s2_exception_to_error_response(exc)


@mcp.tool()
async def recent_photonics(
    context: Context,
    days: int = 30,
    query: Optional[str] = None,
    sources: Optional[List[str]] = None,
    publication_date_or_year: Optional[str] = None,
    min_citation_count: Optional[int] = None,
    fields: Optional[List[str]] = None,
    limit: int = 50,
    token: Optional[str] = None,
) -> Dict:
    """New-paper monitoring for the four photonics publishers, sorted newest
    first. Wraps bulk search with sort=publicationDate:desc over a date window.

    `days` sets the window (last N days); pass `publication_date_or_year`
    (e.g. "2026-01-01:2026-06-30") to override it. `query` is optional — omit
    it to list everything new in the selected venues. `limit` caps how many
    (newest) papers are returned (default 50) so a wide window doesn't flood
    the response; `total` still reports the full count and `truncated` flags
    when more exist. `token` continues bulk pagination. Abstracts are omitted
    by default (pass `fields` to include them). Results are auto-tracked for
    export_bibtex.
    """
    try:
        resolved_keys, venues = resolve_photonics_venues(sources)
        date_range = publication_date_or_year or date_range_from_days(days)
        request = PaperBulkSearchRequest(
            query=query,
            token=token,
            fields=fields or list(_RECENT_FIELDS),
            sort="publicationDate:desc",
            min_citation_count=min_citation_count,
            publication_date_or_year=date_range,
            venue=venues,
        )
        result = await _client().bulk_search_papers(request)
        if isinstance(result, dict) and "error" not in result:
            data = result.get("data") or []
            truncated = len(data) > limit
            if truncated:
                result = {**result, "data": data[:limit]}
            track_papers(result, "recent_photonics")
            result = {
                "sources": resolved_keys,
                "venue_filter": venues,
                "date_range": date_range,
                "returned": len(result.get("data") or []),
                "truncated": truncated,
                **result,
            }
        else:
            track_papers(result, "recent_photonics")
        return result
    except S2ValidationError as exc:
        return s2_exception_to_error_response(exc)
    except S2Error as exc:
        return s2_exception_to_error_response(exc)


@mcp.tool()
async def list_photonics_sources(context: Context) -> Dict:
    """List the photonics publisher presets: source keys, labels, homepages,
    and the exact venue strings each covers. No network call. Use this to
    confirm coverage or explain a gap before searching."""
    return {
        "sources": {
            key: {
                "label": src.label,
                "homepage": src.homepage,
                "venues": list(src.venues),
                **({"note": src.note} if src.note else {}),
            }
            for key, src in PHOTONICS_SOURCES.items()
        },
        "unfilterable_venues": KNOWN_UNFILTERABLE,
        "usage": (
            "Use search_photonics(query, sources=[...]) for topic search or "
            "recent_photonics(days=N, sources=[...]) for new-paper monitoring. "
            "sources defaults to all four keys."
        ),
    }
