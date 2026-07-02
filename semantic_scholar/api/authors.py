"""
Author-related API endpoints for the Semantic Scholar API.
"""

from typing import Dict, List, Optional

from fastmcp import Context

from ..config import ErrorType
from ..core.client import S2Client, make_compat_client
from ..core.exceptions import S2ApiError, S2Error, S2ValidationError
from ..core.requests import (
    AuthorBatchDetailsRequest,
    AuthorDetailsRequest,
    AuthorPapersRequest,
    AuthorSearchRequest,
)
from ..mcp import mcp
from ..tracking_hook import track_papers
from ..tracking_models import Author, AuthorConsolidationResult, AuthorGroup
from ..utils.errors import create_error_response, s2_exception_to_error_response
from ..utils.http import make_request


def _client() -> S2Client:
    return make_compat_client(make_request)


@mcp.tool()
async def author_search(
    context: Context,
    query: str,
    fields: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 100,
) -> Dict:
    try:
        request = AuthorSearchRequest(
            query=query,
            fields=fields,
            offset=offset,
            limit=limit,
        )
        result = await _client().search_authors(request)
        track_papers(result, "author_search")
        return result
    except S2ValidationError as exc:
        return s2_exception_to_error_response(exc)
    except S2Error as exc:
        return s2_exception_to_error_response(exc)


@mcp.tool()
async def author_details(
    context: Context,
    author_id: str,
    fields: Optional[List[str]] = None,
) -> Dict:
    try:
        request = AuthorDetailsRequest(author_id=author_id, fields=fields)
        result = await _client().get_author(request)
        track_papers(result, "author_details")
        return result
    except S2ValidationError as exc:
        return s2_exception_to_error_response(exc)
    except S2ApiError as exc:
        if "404" in exc.message:
            return create_error_response(
                ErrorType.VALIDATION,
                "Author not found",
                {"author_id": author_id},
            )
        return s2_exception_to_error_response(exc)
    except S2Error as exc:
        return s2_exception_to_error_response(exc)


@mcp.tool()
async def author_papers(
    context: Context,
    author_id: str,
    fields: Optional[List[str]] = None,
    offset: int = 0,
    limit: int = 100,
) -> Dict:
    try:
        request = AuthorPapersRequest(
            author_id=author_id,
            fields=fields,
            offset=offset,
            limit=limit,
        )
        result = await _client().get_author_papers(request)
        track_papers(result, "author_papers")
        return result
    except S2ValidationError as exc:
        return s2_exception_to_error_response(exc)
    except S2ApiError as exc:
        if "404" in exc.message:
            return create_error_response(
                ErrorType.VALIDATION,
                "Author not found",
                {"author_id": author_id},
            )
        return s2_exception_to_error_response(exc)
    except S2Error as exc:
        return s2_exception_to_error_response(exc)


@mcp.tool()
async def author_batch_details(
    context: Context,
    author_ids: List[str],
    fields: Optional[str] = None,
) -> Dict:
    try:
        request = AuthorBatchDetailsRequest(author_ids=author_ids, fields=fields)
        result = await _client().batch_authors(request)
        track_papers(result, "author_batch_details")
        return result
    except S2ValidationError as exc:
        return s2_exception_to_error_response(exc)
    except S2Error as exc:
        return s2_exception_to_error_response(exc)


_AUTHOR_CONSOLIDATION_FIELDS = [
    "authorId",
    "name",
    "affiliations",
    "paperCount",
    "citationCount",
    "hIndex",
    "homepage",
    "externalIds",
]


def _normalize_dblp(dblp):
    """Normalize DBLP field to a single string.

    The Semantic Scholar API may return DBLP as either a string or a list of
    strings; this always returns the first value as a string, or None.
    """
    if dblp is None:
        return None
    if isinstance(dblp, list):
        return dblp[0] if dblp else None
    return dblp


def _sort_by_citations(authors):
    return sorted(authors, key=lambda a: a.citationCount or 0, reverse=True)


@mcp.tool()
async def find_duplicate_authors(
    context: Context,
    author_names: List[str],
    match_by_orcid: bool = True,
    match_by_dblp: bool = True,
) -> Dict:
    """Find potential duplicate author records by searching for names and
    grouping results that share an ORCID or DBLP identifier."""
    if not author_names:
        return create_error_response(
            ErrorType.VALIDATION,
            "Please provide at least one author name to search for.",
            {},
        )

    client = _client()
    all_authors: List[Author] = []

    for name in author_names:
        try:
            request = AuthorSearchRequest(query=name, fields=_AUTHOR_CONSOLIDATION_FIELDS, limit=20)
            response = await client.search_authors(request)
        except S2ApiError as exc:
            if "404" in exc.message:
                continue
            return s2_exception_to_error_response(exc)
        except S2Error as exc:
            return s2_exception_to_error_response(exc)

        for item in response.get("data", []):
            try:
                all_authors.append(Author(**item))
            except Exception:
                continue

    if not all_authors:
        return create_error_response(
            ErrorType.VALIDATION,
            f"No authors found for the provided names: {', '.join(author_names)}. "
            "Try different name variations or check spelling.",
            {"author_names": author_names},
        )

    orcid_groups: Dict[str, List[Author]] = {}
    dblp_groups: Dict[str, List[Author]] = {}
    seen_author_ids: set = set()

    for author in all_authors:
        if not author.authorId or author.authorId in seen_author_ids:
            continue
        seen_author_ids.add(author.authorId)

        if match_by_orcid and author.externalIds and author.externalIds.ORCID:
            orcid_groups.setdefault(author.externalIds.ORCID, []).append(author)

        if match_by_dblp and author.externalIds and author.externalIds.DBLP:
            dblp = _normalize_dblp(author.externalIds.DBLP)
            if dblp is not None:
                dblp_groups.setdefault(dblp, []).append(author)

    author_groups: List[AuthorGroup] = []
    processed_author_ids: set = set()

    for orcid, authors in orcid_groups.items():
        if len(authors) > 1:
            sorted_authors = _sort_by_citations(authors)
            primary, candidates = sorted_authors[0], sorted_authors[1:]
            processed_author_ids.update(a.authorId for a in sorted_authors if a.authorId)
            author_groups.append(
                AuthorGroup(
                    primary_author=primary,
                    candidates=candidates,
                    match_reasons=[f"same_orcid:{orcid}"],
                )
            )

    for dblp, authors in dblp_groups.items():
        remaining = [a for a in authors if a.authorId and a.authorId not in processed_author_ids]
        if len(remaining) > 1:
            sorted_authors = _sort_by_citations(remaining)
            primary, candidates = sorted_authors[0], sorted_authors[1:]
            processed_author_ids.update(a.authorId for a in sorted_authors if a.authorId)
            author_groups.append(
                AuthorGroup(
                    primary_author=primary,
                    candidates=candidates,
                    match_reasons=[f"same_dblp:{dblp}"],
                )
            )

    if not author_groups:
        return {
            "groups": [],
            "message": (
                f"No potential duplicate authors found for: {', '.join(author_names)}. "
                "The authors found have unique external identifiers, or no external IDs "
                "are available to match against."
            ),
        }

    return {"groups": [g.model_dump(exclude_none=True) for g in author_groups]}


@mcp.tool()
async def consolidate_authors(
    context: Context,
    author_ids: List[str],
    confirm_merge: bool = False,
) -> Dict:
    """Preview or confirm merging of duplicate author records. This creates a
    local consolidated view only — it does not modify Semantic Scholar's data."""
    if not author_ids or len(author_ids) < 2:
        return create_error_response(
            ErrorType.VALIDATION,
            "Please provide at least two author IDs to consolidate.",
            {"author_ids": author_ids},
        )

    client = _client()
    authors: List[Author] = []

    for author_id in author_ids:
        try:
            request = AuthorDetailsRequest(author_id=author_id, fields=_AUTHOR_CONSOLIDATION_FIELDS)
            response = await client.get_author(request)
        except S2ApiError as exc:
            if "404" in exc.message:
                return create_error_response(
                    ErrorType.VALIDATION, "Author not found", {"author_id": author_id}
                )
            return s2_exception_to_error_response(exc)
        except S2Error as exc:
            return s2_exception_to_error_response(exc)

        try:
            authors.append(Author(**response))
        except Exception:
            return create_error_response(
                ErrorType.API_ERROR,
                "Received a malformed author record from the API.",
                {"author_id": author_id},
            )

    if len(authors) < 2:
        return create_error_response(
            ErrorType.API_ERROR, "Could not retrieve enough author records to consolidate.", {}
        )

    match_type = "user_confirmed"
    confidence = None

    orcids = [a.externalIds.ORCID for a in authors if a.externalIds and a.externalIds.ORCID]
    if len(orcids) >= 2 and len(set(orcids)) == 1:
        match_type, confidence = "orcid", 1.0

    dblps = [_normalize_dblp(a.externalIds.DBLP) for a in authors if a.externalIds and a.externalIds.DBLP]
    dblps = [d for d in dblps if d is not None]
    if match_type == "user_confirmed" and len(dblps) >= 2 and len(set(dblps)) == 1:
        match_type, confidence = "dblp", 0.95

    sorted_authors = _sort_by_citations(authors)
    primary = sorted_authors[0]

    merged_affiliations: List[str] = []
    merged_aliases: List[str] = []
    for author in authors:
        for aff in author.affiliations or []:
            if aff not in merged_affiliations:
                merged_affiliations.append(aff)
        if author.name and author.name not in merged_aliases:
            merged_aliases.append(author.name)
    if primary.name and primary.name in merged_aliases:
        merged_aliases.remove(primary.name)

    total_papers = sum(a.paperCount or 0 for a in authors)
    total_citations = sum(a.citationCount or 0 for a in authors)

    source_hindices = [str(a.hIndex) for a in authors if a.hIndex is not None]
    if source_hindices:
        note = (
            "Note: h-index is not set for merged profiles because it cannot be accurately "
            "computed from multiple author records. The source authors' h-indices are: "
            f"{', '.join(source_hindices)}."
        )
    else:
        note = (
            "Note: h-index is not set for merged profiles because it cannot be accurately "
            "computed from multiple author records."
        )

    best_external_ids = primary.externalIds
    if not best_external_ids:
        for author in authors:
            if author.externalIds:
                best_external_ids = author.externalIds
                break

    merged_author = Author(
        authorId=primary.authorId,
        name=primary.name,
        affiliations=merged_affiliations or None,
        paperCount=total_papers,
        citationCount=total_citations,
        hIndex=None,
        aliases=merged_aliases or None,
        homepage=primary.homepage,
        externalIds=best_external_ids,
    )

    result = AuthorConsolidationResult(
        merged_author=merged_author,
        source_authors=authors,
        match_type=match_type,
        confidence=confidence,
        is_preview=not confirm_merge,
        notes=[note],
    )
    # `confidence` is a meaningful explicit None (no ORCID/DBLP match, i.e. a
    # user-confirmed merge), so it must stay present in the response even
    # though exclude_none=True drops other unset optional fields.
    dumped = result.model_dump(exclude_none=True)
    dumped.setdefault("confidence", None)
    return dumped
