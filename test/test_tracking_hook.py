from semantic_scholar.paper_tracker import PaperTracker
from semantic_scholar.tracking_hook import track_papers


def test_tracks_papers_from_data_list():
    response = {"total": 1, "offset": 0, "data": [{"paperId": "p1", "title": "T1"}]}

    track_papers(response, "paper_relevance_search")

    tracker = PaperTracker.get_instance()
    assert tracker.count() == 1
    assert tracker.is_tracked("p1")


def test_tracks_single_paper_dict():
    response = {"paperId": "p1", "title": "Solo Paper"}

    track_papers(response, "paper_details")

    assert PaperTracker.get_instance().is_tracked("p1")


def test_tracks_batch_list_response_skipping_none():
    response = [{"paperId": "p1"}, None, {"paperId": "p2"}]

    track_papers(response, "paper_batch_details")

    assert PaperTracker.get_instance().count() == 2


def test_unwraps_citing_and_cited_paper():
    response = {"data": [{"citingPaper": {"paperId": "p1"}}, {"citedPaper": {"paperId": "p2"}}]}

    track_papers(response, "paper_citations")

    assert PaperTracker.get_instance().count() == 2


def test_unwraps_snippet_paper_wrapper():
    response = {"data": [{"snippet": {"text": "..."}, "paper": {"paperId": "p1"}}]}

    track_papers(response, "snippet_search")

    assert PaperTracker.get_instance().is_tracked("p1")


def test_unwraps_nested_papers_key():
    response = {"authorId": "a1", "name": "Jane", "papers": [{"paperId": "p1"}, {"paperId": "p2"}]}

    track_papers(response, "author_details")

    assert PaperTracker.get_instance().count() == 2


def test_tracks_recommended_papers():
    response = {"recommendedPapers": [{"paperId": "p1"}, {"paperId": "p2"}]}

    track_papers(response, "get_paper_recommendations_single")

    assert PaperTracker.get_instance().count() == 2


def test_ignores_error_response():
    response = {"error": {"type": "validation", "message": "bad", "details": {}}}

    track_papers(response, "paper_details")

    assert PaperTracker.get_instance().count() == 0


def test_ignores_author_only_responses():
    response = {"total": 1, "data": [{"authorId": "a1", "name": "Jane"}]}

    track_papers(response, "author_search")

    assert PaperTracker.get_instance().count() == 0


def test_never_raises_on_malformed_input():
    # A non-string paperId fails Paper validation; track_papers must swallow it.
    track_papers({"data": [{"paperId": 12345}]}, "paper_details")
    # Non-dict, non-list inputs must also be handled without raising.
    track_papers("not a dict or list", "weird_tool")
    track_papers(None, "weird_tool")

    assert PaperTracker.get_instance().count() == 0
