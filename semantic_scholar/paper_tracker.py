"""Session-based paper tracking for the Semantic Scholar MCP server.

This module provides a singleton tracker that keeps track of papers
retrieved during a session, enabling features like BibTeX export of
all papers from a research session.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from .tracking_models import Paper
from .utils.logger import logger


@dataclass
class TrackedPaper:
    """A paper with tracking metadata."""

    paper: Paper
    source_tool: str
    tracked_at: datetime = field(default_factory=datetime.now)


class PaperTracker:
    """Singleton tracker for papers retrieved during a session.

    Thread-safe implementation using double-checked locking.

    Usage:
        tracker = PaperTracker.get_instance()
        tracker.track(paper, "paper_relevance_search")
        all_papers = tracker.get_all_papers()
        tracker.clear()
    """

    _instance: ClassVar["PaperTracker | None"] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        self._papers: dict[str, TrackedPaper] = {}
        self._papers_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "PaperTracker":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = PaperTracker()
        assert cls._instance is not None
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        with cls._lock:
            cls._instance = None

    def track(self, paper: Paper, source_tool: str) -> None:
        if paper.paperId:
            with self._papers_lock:
                self._papers[paper.paperId] = TrackedPaper(
                    paper=paper,
                    source_tool=source_tool,
                )
                logger.debug("Tracking paper: %s (source: %s)", paper.paperId, source_tool)

    def track_many(self, papers: list[Paper], source_tool: str) -> None:
        logger.debug("Tracking %d papers (source: %s)", len(papers), source_tool)
        for paper in papers:
            self.track(paper, source_tool)

    def get_all_papers(self) -> list[Paper]:
        with self._papers_lock:
            sorted_tracked = sorted(self._papers.values(), key=lambda tp: tp.tracked_at)
            return [tp.paper for tp in sorted_tracked]

    def get_papers_by_tool(self, tool_name: str) -> list[Paper]:
        with self._papers_lock:
            matching = [tp for tp in self._papers.values() if tp.source_tool == tool_name]
            sorted_tracked = sorted(matching, key=lambda tp: tp.tracked_at)
            return [tp.paper for tp in sorted_tracked]

    def get_papers_by_ids(self, paper_ids: list[str]) -> list[Paper]:
        with self._papers_lock:
            papers = []
            for paper_id in paper_ids:
                if paper_id in self._papers:
                    papers.append(self._papers[paper_id].paper)
            return papers

    def get_tracked_paper(self, paper_id: str) -> TrackedPaper | None:
        with self._papers_lock:
            return self._papers.get(paper_id)

    def is_tracked(self, paper_id: str) -> bool:
        with self._papers_lock:
            return paper_id in self._papers

    def count(self) -> int:
        with self._papers_lock:
            return len(self._papers)

    def clear(self) -> None:
        with self._papers_lock:
            count = len(self._papers)
            self._papers.clear()
            logger.info("Cleared %d tracked papers", count)

    def get_tool_summary(self) -> dict[str, int]:
        with self._papers_lock:
            summary: dict[str, int] = {}
            for tracked in self._papers.values():
                tool = tracked.source_tool
                summary[tool] = summary.get(tool, 0) + 1
            return summary


def get_tracker() -> PaperTracker:
    """Get the global paper tracker instance."""
    return PaperTracker.get_instance()
