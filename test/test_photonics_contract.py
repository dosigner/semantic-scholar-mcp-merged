import datetime

import pytest

import semantic_scholar.api.photonics as photonics_api
from semantic_scholar.core.exceptions import S2ValidationError
from semantic_scholar.paper_tracker import PaperTracker

pytestmark = pytest.mark.asyncio


# All venue strings, in the deterministic merge order resolve_photonics_venues
# produces for sources=None (registry insertion order, deduped).
def _all_venues():
    _, venues = photonics_api.resolve_photonics_venues(None)
    return venues


_DEFAULT_FIELDS_STR = ",".join(photonics_api._DEFAULT_FIELDS)


# --- registry / helper shape ---------------------------------------------------


async def test_registry_shape():
    keys = list(photonics_api.PHOTONICS_SOURCES.keys())
    assert keys == ["optica", "spie", "nature_lsa", "nature_photonics"]
    seen = set()
    for src in photonics_api.PHOTONICS_SOURCES.values():
        assert src.venues, f"{src.key} has no venues"
        for v in src.venues:
            # comma rule: no venue string may contain a comma (inexpressible in
            # the comma-joined filter).
            assert "," not in v, f"venue contains comma: {v!r}"
            assert v not in seen, f"duplicate venue across sources: {v!r}"
            seen.add(v)


async def test_resolve_all_default():
    keys, venues = photonics_api.resolve_photonics_venues(None)
    assert keys == ["optica", "spie", "nature_lsa", "nature_photonics"]
    assert "Optics Express" in venues
    assert "Nature Photonics" in venues
    assert len(venues) == len(set(venues))


async def test_resolve_subset_preserves_order_and_dedupes():
    keys, venues = photonics_api.resolve_photonics_venues(
        ["nature_photonics", "nature_lsa", "nature_photonics"]
    )
    assert keys == ["nature_photonics", "nature_lsa"]
    assert venues == ["Nature Photonics", "Light: Science and Applications"]


async def test_resolve_unknown_key_raises():
    with pytest.raises(S2ValidationError) as exc_info:
        photonics_api.resolve_photonics_venues(["optica", "bogus"])
    assert exc_info.value.details["valid_sources"] == [
        "optica",
        "spie",
        "nature_lsa",
        "nature_photonics",
    ]


async def test_date_range_from_days_deterministic():
    out = photonics_api.date_range_from_days(30, today=datetime.date(2026, 7, 2))
    assert out == "2026-06-02:"


async def test_date_range_from_days_rejects_zero():
    with pytest.raises(S2ValidationError):
        photonics_api.date_range_from_days(0)


# --- search_photonics ----------------------------------------------------------


async def test_search_photonics_happy_path(mock_make_request):
    payload = {"total": 1, "offset": 0, "data": [{"paperId": "p1"}]}
    mock_make_request.install(photonics_api).queue_responses(payload)

    result = await photonics_api.search_photonics.fn(
        None, query="diffractive neural network", limit=15
    )

    # response augmented with sources + venue_filter, original payload preserved
    assert result["sources"] == ["optica", "spie", "nature_lsa", "nature_photonics"]
    assert result["venue_filter"] == _all_venues()
    assert result["total"] == 1 and result["data"] == [{"paperId": "p1"}]

    assert len(mock_make_request.calls) == 1
    call = mock_make_request.calls[0]
    assert call["endpoint"] == "/paper/search"
    assert call["params"]["query"] == "diffractive neural network"
    assert call["params"]["limit"] == 15
    assert call["params"]["venue"] == ",".join(_all_venues())
    assert call["params"]["fields"] == _DEFAULT_FIELDS_STR


async def test_search_photonics_subset_venue_filter(mock_make_request):
    mock_make_request.install(photonics_api).queue_responses(
        {"total": 0, "offset": 0, "data": []}
    )

    await photonics_api.search_photonics.fn(
        None, query="wavefront", sources=["nature_photonics"]
    )

    call = mock_make_request.calls[0]
    assert call["params"]["venue"] == "Nature Photonics"


async def test_search_photonics_unknown_source_returns_error(mock_make_request):
    mock_make_request.install(photonics_api)  # nothing queued; must not be called

    result = await photonics_api.search_photonics.fn(
        None, query="x", sources=["nope"]
    )

    assert result["error"]["type"] == "validation"
    assert result["error"]["details"]["valid_sources"]
    assert mock_make_request.calls == []


async def test_search_photonics_tracks_papers(mock_make_request):
    mock_make_request.install(photonics_api).queue_responses(
        {"total": 1, "offset": 0, "data": [{"paperId": "p1", "title": "T"}]}
    )

    await photonics_api.search_photonics.fn(None, query="x")

    tracker = PaperTracker.get_instance()
    assert tracker.count() == 1
    assert tracker.get_papers_by_tool("search_photonics")[0].paperId == "p1"


# --- recent_photonics ----------------------------------------------------------


async def test_recent_photonics_explicit_range(mock_make_request):
    payload = {"total": 2, "data": [{"paperId": "a"}, {"paperId": "b"}]}
    mock_make_request.install(photonics_api).queue_responses(payload)

    result = await photonics_api.recent_photonics.fn(
        None,
        sources=["nature_lsa"],
        publication_date_or_year="2026-01-01:2026-06-30",
    )

    assert result["date_range"] == "2026-01-01:2026-06-30"
    call = mock_make_request.calls[0]
    assert call["endpoint"] == "/paper/search/bulk"
    assert call["params"]["sort"] == "publicationDate:desc"
    assert call["params"]["publicationDateOrYear"] == "2026-01-01:2026-06-30"
    assert call["params"]["venue"] == "Light: Science and Applications"
    # query omitted -> no query param
    assert "query" not in call["params"]


async def test_recent_photonics_days_window(mock_make_request):
    mock_make_request.install(photonics_api).queue_responses({"total": 0, "data": []})

    await photonics_api.recent_photonics.fn(None, days=60, query="laser")

    call = mock_make_request.calls[0]
    # a days-based window produces an open-ended "<date>:" range
    assert call["params"]["publicationDateOrYear"].endswith(":")
    assert call["params"]["query"] == "laser"
    assert call["params"]["sort"] == "publicationDate:desc"


async def test_recent_photonics_caps_results(mock_make_request):
    # 5 papers returned but limit=2 -> newest 2 kept, truncated flagged, total intact
    payload = {"total": 5, "data": [{"paperId": f"p{i}"} for i in range(5)]}
    mock_make_request.install(photonics_api).queue_responses(payload)

    result = await photonics_api.recent_photonics.fn(None, days=30, limit=2)

    assert result["total"] == 5
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert [p["paperId"] for p in result["data"]] == ["p0", "p1"]
    # only the returned (capped) papers are tracked, not all 5
    assert PaperTracker.get_instance().count() == 2


async def test_recent_photonics_not_truncated_when_under_limit(mock_make_request):
    mock_make_request.install(photonics_api).queue_responses(
        {"total": 2, "data": [{"paperId": "a"}, {"paperId": "b"}]}
    )

    result = await photonics_api.recent_photonics.fn(None, days=30, limit=50)

    assert result["truncated"] is False
    assert result["returned"] == 2


async def test_recent_photonics_default_fields_omit_abstract(mock_make_request):
    mock_make_request.install(photonics_api).queue_responses({"total": 0, "data": []})

    await photonics_api.recent_photonics.fn(None, days=30)

    call = mock_make_request.calls[0]
    assert "abstract" not in call["params"]["fields"]


async def test_recent_photonics_tracks_papers(mock_make_request):
    mock_make_request.install(photonics_api).queue_responses(
        {"total": 1, "data": [{"paperId": "r1"}]}
    )

    await photonics_api.recent_photonics.fn(None, days=30)

    tracker = PaperTracker.get_instance()
    assert tracker.get_papers_by_tool("recent_photonics")[0].paperId == "r1"


# --- list_photonics_sources ----------------------------------------------------


async def test_list_photonics_sources_no_network(mock_make_request):
    mock_make_request.install(photonics_api)  # nothing queued; must not be called

    result = await photonics_api.list_photonics_sources.fn(None)

    assert set(result["sources"].keys()) == {
        "optica",
        "spie",
        "nature_lsa",
        "nature_photonics",
    }
    assert result["sources"]["optica"]["venues"]
    assert "note" in result["sources"]["spie"]  # SPIE coverage caveat surfaced
    assert result["unfilterable_venues"] == {}
    assert mock_make_request.calls == []


# --- error passthrough ---------------------------------------------------------


async def test_search_photonics_rate_limit_passthrough(
    mock_make_request, mock_error_response
):
    mock_make_request.install(photonics_api).queue_responses(
        mock_error_response(status_code=429)
    )

    result = await photonics_api.search_photonics.fn(None, query="x")

    assert result["error"]["type"] == "rate_limit"
