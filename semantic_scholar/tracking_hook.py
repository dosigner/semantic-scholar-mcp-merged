"""Best-effort extraction of paper dicts from raw Semantic Scholar API
responses, used to auto-populate the session PaperTracker so export_bibtex
works without requiring a separate manual tracking step.

track_papers() must never raise: a parsing failure here must never break the
primary response of the tool that called it.
"""

from typing import Any

from .paper_tracker import get_tracker
from .tracking_models import Paper
from .utils.logger import logger


def _unwrap(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    for wrapper_key in ("citingPaper", "citedPaper", "paper"):
        nested = item.get(wrapper_key)
        if isinstance(nested, dict):
            return nested
    if "paperId" in item:
        return item
    return None


def _candidate_dicts(response: Any) -> list[dict]:
    if isinstance(response, dict):
        if "error" in response:
            return []
        for list_key in ("papers", "data", "recommendedPapers"):
            items = response.get(list_key)
            if isinstance(items, list):
                unwrapped = [_unwrap(item) for item in items]
                return [u for u in unwrapped if u is not None]
        if "paperId" in response:
            return [response]
        return []
    if isinstance(response, list):
        unwrapped = [_unwrap(item) for item in response]
        return [u for u in unwrapped if u is not None]
    return []


def track_papers(response: Any, source_tool: str) -> None:
    """Best-effort: parse papers out of a raw API response and record them in
    the session PaperTracker. Never raises."""
    try:
        candidates = _candidate_dicts(response)
        if not candidates:
            return
        papers: list[Paper] = []
        for item in candidates:
            try:
                papers.append(Paper(**item))
            except Exception:
                continue
        if papers:
            get_tracker().track_many(papers, source_tool)
    except Exception as exc:
        logger.warning("track_papers: failed to record papers from %s: %s", source_tool, exc)
