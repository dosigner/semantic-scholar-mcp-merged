"""Session paper tracking and BibTeX export tools."""

import os
from typing import Dict, List, Optional

from fastmcp import Context

from ..bibtex import BibTeXExportConfig, BibTeXFieldConfig, export_papers_to_bibtex
from ..config import ErrorType
from ..core.client import S2Client, make_compat_client
from ..core.exceptions import S2ApiError, S2Error
from ..core.requests import PaperDetailsRequest
from ..mcp import mcp
from ..paper_tracker import get_tracker
from ..tracking_models import Paper
from ..utils.errors import create_error_response
from ..utils.http import make_request

_BIBTEX_PAPER_FIELDS = [
    "paperId",
    "title",
    "abstract",
    "year",
    "authors",
    "venue",
    "publicationTypes",
    "journal",
    "externalIds",
    "openAccessPdf",
    "fieldsOfStudy",
    "publicationDate",
    "publicationVenue",
]


def _client() -> S2Client:
    return make_compat_client(make_request)


def _is_sparse_for_bibtex(paper: Paper) -> bool:
    """A tracked paper lacks the metadata needed for a *correct* BibTeX entry:
    without `publicationTypes` or a structured `journal` object, entry-type
    detection falls back to guessing from the venue string, which misclassifies
    journals like "Optics Express" as `@misc`. This is true even when the
    paper already has a DOI/venue from a search tool's sparse default fields."""
    return bool(
        paper.paperId
        and not paper.publicationTypes
        and paper.journal is None
    )


@mcp.tool()
async def list_tracked_papers(
    context: Context,
    source_tool: Optional[str] = None,
) -> Dict:
    """List papers tracked so far during this session, optionally filtered by
    which tool retrieved them (e.g. "paper_relevance_search")."""
    tracker = get_tracker()
    papers = tracker.get_papers_by_tool(source_tool) if source_tool else tracker.get_all_papers()

    if not papers:
        message = (
            f"No papers tracked from '{source_tool}'."
            if source_tool
            else "No papers tracked in this session."
        ) + " Use paper_relevance_search, paper_details, or other tools to find papers first."
        return {"count": 0, "papers": [], "message": message}

    return {
        "count": len(papers),
        "papers": [p.model_dump(exclude_none=True) for p in papers],
    }


@mcp.tool()
async def clear_tracked_papers(context: Context) -> Dict:
    """Clear all papers tracked so far during this session."""
    tracker = get_tracker()
    count = tracker.count()
    tracker.clear()
    return {"cleared": count, "message": f"Cleared {count} tracked papers from this session."}


@mcp.tool()
async def export_bibtex(
    context: Context,
    paper_ids: Optional[List[str]] = None,
    include_abstract: bool = False,
    include_url: bool = True,
    include_doi: bool = True,
    enrich: bool = True,
    cite_key_format: str = "author_year",
    file_path: Optional[str] = None,
) -> Dict:
    """Export tracked papers (or specific paper IDs) to BibTeX format.

    When `enrich` is True (default), papers missing key BibTeX metadata
    (DOI/venue/journal) are re-fetched with full fields before rendering;
    set it to False to skip network calls and export only what's already
    tracked.
    """
    tracker = get_tracker()

    if paper_ids:
        papers = tracker.get_papers_by_ids(paper_ids)
        found_ids = {p.paperId for p in papers if p.paperId}
        missing_ids = [pid for pid in paper_ids if pid not in found_ids]

        if missing_ids:
            client = _client()
            for pid in missing_ids:
                try:
                    response = await client.get_paper(
                        PaperDetailsRequest(paper_id=pid, fields=_BIBTEX_PAPER_FIELDS)
                    )
                except (S2ApiError, S2Error):
                    continue
                try:
                    paper = Paper(**response)
                except Exception:
                    continue
                papers.append(paper)
                tracker.track(paper, "export_bibtex")

        if not papers:
            return create_error_response(
                ErrorType.VALIDATION,
                "No papers found with the provided IDs. Please verify the paper IDs, "
                "or use list_tracked_papers() to see available papers.",
                {"paper_ids": paper_ids},
            )
    else:
        papers = tracker.get_all_papers()
        if not papers:
            return create_error_response(
                ErrorType.VALIDATION,
                "No papers tracked in this session to export. Use paper_relevance_search, "
                "paper_details, or other tools to find papers first, then call export_bibtex().",
                {},
            )

    if enrich:
        client = _client()
        enriched: List[Paper] = []
        for paper in papers:
            if _is_sparse_for_bibtex(paper):
                try:
                    response = await client.get_paper(
                        PaperDetailsRequest(paper_id=paper.paperId, fields=_BIBTEX_PAPER_FIELDS)
                    )
                    rich = Paper(**response)
                except Exception:
                    enriched.append(paper)
                    continue
                enriched.append(rich)
                tracker.track(rich, "export_bibtex")
            else:
                enriched.append(paper)
        papers = enriched

    field_config = BibTeXFieldConfig(
        include_abstract=include_abstract,
        include_url=include_url,
        include_doi=include_doi,
    )
    export_config = BibTeXExportConfig(fields=field_config, cite_key_format=cite_key_format)
    bibtex_output = export_papers_to_bibtex(papers, export_config)

    if file_path:
        expanded_path = os.path.expanduser(file_path)
        abs_path = os.path.abspath(expanded_path)
        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(bibtex_output)
        except OSError as exc:
            return create_error_response(
                ErrorType.API_ERROR,
                f"Error writing to file '{abs_path}': {exc}",
                {"file_path": abs_path},
            )
        return {
            "count": len(papers),
            "file_path": abs_path,
            "message": f"Successfully exported {len(papers)} papers to BibTeX format.",
        }

    return {"count": len(papers), "bibtex": bibtex_output}
