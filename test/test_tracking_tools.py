import os

import pytest

import semantic_scholar.api.tracking as tracking_api
from semantic_scholar.paper_tracker import PaperTracker
from semantic_scholar.tracking_models import Author, Paper

pytestmark = pytest.mark.asyncio


def _track(paper_id, title, year=2020, source="search_papers"):
    paper = Paper(
        paperId=paper_id,
        title=title,
        year=year,
        authors=[Author(authorId="a1", name="Jane Doe")],
    )
    PaperTracker.get_instance().track(paper, source)
    return paper


async def test_list_tracked_papers_empty():
    result = await tracking_api.list_tracked_papers.fn(None)

    assert result["count"] == 0
    assert "No papers tracked" in result["message"]


async def test_list_tracked_papers_returns_all():
    _track("p1", "Paper 1")
    _track("p2", "Paper 2")

    result = await tracking_api.list_tracked_papers.fn(None)

    assert result["count"] == 2
    titles = {p["title"] for p in result["papers"]}
    assert titles == {"Paper 1", "Paper 2"}


async def test_list_tracked_papers_filters_by_tool():
    _track("p1", "Paper 1", source="search_papers")
    _track("p2", "Paper 2", source="get_paper_recommendations_single")

    result = await tracking_api.list_tracked_papers.fn(None, source_tool="search_papers")

    assert result["count"] == 1
    assert result["papers"][0]["paperId"] == "p1"


async def test_clear_tracked_papers():
    _track("p1", "Paper 1")
    _track("p2", "Paper 2")

    result = await tracking_api.clear_tracked_papers.fn(None)

    assert result["cleared"] == 2
    assert PaperTracker.get_instance().count() == 0


async def test_export_bibtex_no_papers_returns_error():
    result = await tracking_api.export_bibtex.fn(None)

    assert result["error"]["type"] == "validation"


async def test_export_bibtex_exports_tracked_papers(mock_make_request):
    mock_make_request.install(tracking_api)
    _track("p1", "Test Paper", 2020)

    result = await tracking_api.export_bibtex.fn(None)

    assert result["count"] == 1
    assert "Test Paper" in result["bibtex"]


async def test_export_bibtex_specific_ids_only(mock_make_request):
    mock_make_request.install(tracking_api)
    _track("p1", "Paper One", 2020)
    _track("p2", "Paper Two", 2021)

    result = await tracking_api.export_bibtex.fn(None, paper_ids=["p1"])

    assert "Paper One" in result["bibtex"]
    assert "Paper Two" not in result["bibtex"]


async def test_export_bibtex_fetches_untracked_id_from_api(mock_make_request):
    mock_make_request.install(tracking_api).queue_responses(
        {"paperId": "remote1", "title": "Remote Paper", "year": 2022}
    )

    result = await tracking_api.export_bibtex.fn(None, paper_ids=["remote1"])

    assert "Remote Paper" in result["bibtex"]
    assert PaperTracker.get_instance().is_tracked("remote1")


async def test_export_bibtex_missing_id_after_fetch_attempt(mock_make_request, mock_error_response):
    mock_make_request.install(tracking_api).queue_responses(mock_error_response(status_code=404))

    result = await tracking_api.export_bibtex.fn(None, paper_ids=["nonexistent"])

    assert result["error"]["type"] == "validation"


async def test_export_bibtex_writes_to_file(mock_make_request, tmp_path):
    mock_make_request.install(tracking_api)
    _track("p1", "File Paper", 2020)
    output_file = str(tmp_path / "refs.bib")

    result = await tracking_api.export_bibtex.fn(None, file_path=output_file)

    assert result["file_path"] == os.path.abspath(output_file)
    with open(output_file) as f:
        content = f.read()
    assert "File Paper" in content


async def test_export_bibtex_enriches_sparse_tracked_paper(mock_make_request):
    PaperTracker.get_instance().track(
        Paper(paperId="p1", title="Sparse Paper", year=2020,
              authors=[Author(authorId="a1", name="Jane Doe")]),
        "paper_relevance_search",
    )
    mock_make_request.install(tracking_api).queue_responses({
        "paperId": "p1", "title": "Sparse Paper", "year": 2020,
        "authors": [{"authorId": "a1", "name": "Jane Doe"}],
        "externalIds": {"DOI": "10.1234/enriched"},
        "publicationTypes": ["JournalArticle"],
        "journal": {"name": "Nature"},
    })

    result = await tracking_api.export_bibtex.fn(None)

    assert "10.1234/enriched" in result["bibtex"]
    assert "@article" in result["bibtex"]


async def test_export_bibtex_enrich_false_keeps_sparse(mock_make_request):
    PaperTracker.get_instance().track(
        Paper(paperId="p1", title="Sparse Paper", year=2020,
              authors=[Author(authorId="a1", name="Jane Doe")]),
        "paper_relevance_search",
    )
    mock_make_request.install(tracking_api)  # nothing queued; must not be called

    result = await tracking_api.export_bibtex.fn(None, enrich=False)

    assert "Sparse Paper" in result["bibtex"]
    assert "@misc" in result["bibtex"]
    assert "10.1234" not in result["bibtex"]


async def test_export_bibtex_enrichment_failure_falls_back(mock_make_request, mock_error_response):
    PaperTracker.get_instance().track(
        Paper(paperId="p1", title="Sparse Paper", year=2020,
              authors=[Author(authorId="a1", name="Jane Doe")]),
        "paper_relevance_search",
    )
    mock_make_request.install(tracking_api).queue_responses(mock_error_response(status_code=404))

    result = await tracking_api.export_bibtex.fn(None)

    assert isinstance(result, dict)
    assert "Sparse Paper" in result["bibtex"]
