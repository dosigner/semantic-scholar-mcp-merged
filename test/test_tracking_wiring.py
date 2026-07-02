import pytest

import semantic_scholar.api.authors as authors_api
import semantic_scholar.api.papers as papers_api
import semantic_scholar.api.recommendations as recommendations_api
from semantic_scholar.paper_tracker import PaperTracker

pytestmark = pytest.mark.asyncio


async def test_paper_relevance_search_tracks_results(mock_make_request):
    payload = {"total": 1, "offset": 0, "data": [{"paperId": "p1", "title": "T1"}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    await papers_api.paper_relevance_search.fn(None, query="attention")

    assert PaperTracker.get_instance().is_tracked("p1")


async def test_paper_details_tracks_result(mock_make_request):
    payload = {"paperId": "p1", "title": "Solo"}
    mock_make_request.install(papers_api).queue_responses(payload)

    await papers_api.paper_details.fn(None, paper_id="p1")

    assert PaperTracker.get_instance().is_tracked("p1")


async def test_paper_batch_details_tracks_all(mock_make_request):
    payload = [{"paperId": "p1"}, None, {"paperId": "p2"}]
    mock_make_request.install(papers_api).queue_responses(payload)

    await papers_api.paper_batch_details.fn(None, paper_ids=["p1", "p2", "missing"])

    assert PaperTracker.get_instance().count() == 2


async def test_snippet_search_tracks_wrapped_papers(mock_make_request):
    payload = {"data": [{"snippet": {"text": "..."}, "paper": {"paperId": "p1"}}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    await papers_api.snippet_search.fn(None, query="turbulence")

    assert PaperTracker.get_instance().is_tracked("p1")


async def test_author_details_does_not_track_bare_author(mock_make_request):
    payload = {"authorId": "a1", "name": "Jane Doe"}
    mock_make_request.install(authors_api).queue_responses(payload)

    await authors_api.author_details.fn(None, author_id="a1")

    assert PaperTracker.get_instance().count() == 0


async def test_author_details_tracks_nested_papers(mock_make_request):
    payload = {"authorId": "a1", "name": "Jane Doe", "papers": [{"paperId": "p1"}]}
    mock_make_request.install(authors_api).queue_responses(payload)

    await authors_api.author_details.fn(None, author_id="a1")

    assert PaperTracker.get_instance().is_tracked("p1")


async def test_get_paper_recommendations_single_tracks_results(mock_make_request):
    payload = {"recommendedPapers": [{"paperId": "p1"}, {"paperId": "p2"}]}
    mock_make_request.install(recommendations_api).queue_responses(payload)

    await recommendations_api.get_paper_recommendations_single.fn(None, paper_id="seed")

    assert PaperTracker.get_instance().count() == 2


async def test_tracking_failure_does_not_break_primary_response(mock_make_request):
    payload = {"total": 1, "offset": 0, "data": [{"paperId": 12345}]}
    mock_make_request.install(papers_api).queue_responses(payload)

    result = await papers_api.paper_relevance_search.fn(None, query="attention")

    assert result == payload
    assert PaperTracker.get_instance().count() == 0
