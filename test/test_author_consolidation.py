import pytest

import semantic_scholar.api.authors as authors_api

pytestmark = pytest.mark.asyncio


async def test_find_duplicate_authors_empty_names(mock_make_request):
    result = await authors_api.find_duplicate_authors.fn(None, author_names=[])

    assert result["error"]["type"] == "validation"
    assert mock_make_request.calls == []


async def test_find_duplicate_authors_with_orcid_match(mock_make_request):
    mock_response = {
        "total": 2,
        "data": [
            {
                "authorId": "1",
                "name": "John Smith",
                "citationCount": 1000,
                "externalIds": {"ORCID": "0000-0001-2345-6789"},
            },
            {
                "authorId": "2",
                "name": "J. Smith",
                "citationCount": 500,
                "externalIds": {"ORCID": "0000-0001-2345-6789"},
            },
        ],
    }
    mock_make_request.install(authors_api).queue_responses(mock_response)

    result = await authors_api.find_duplicate_authors.fn(None, author_names=["John Smith"])

    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["primary_author"]["authorId"] == "1"
    assert len(group["candidates"]) == 1
    assert "same_orcid" in group["match_reasons"][0]


async def test_find_duplicate_authors_no_duplicates(mock_make_request):
    mock_response = {
        "total": 2,
        "data": [
            {"authorId": "1", "name": "John Smith", "externalIds": {"ORCID": "0000-0001-1111-1111"}},
            {"authorId": "2", "name": "Jane Doe", "externalIds": {"ORCID": "0000-0002-2222-2222"}},
        ],
    }
    mock_make_request.install(authors_api).queue_responses(mock_response)

    result = await authors_api.find_duplicate_authors.fn(None, author_names=["John Smith"])

    assert result["groups"] == []
    assert "no potential duplicate" in result["message"].lower()


async def test_find_duplicate_authors_with_dblp_match(mock_make_request):
    mock_response = {
        "total": 2,
        "data": [
            {
                "authorId": "1", "name": "John Smith", "citationCount": 1000,
                "externalIds": {"DBLP": "homepages/s/JohnSmith"},
            },
            {
                "authorId": "2", "name": "J. Smith", "citationCount": 500,
                "externalIds": {"DBLP": "homepages/s/JohnSmith"},
            },
        ],
    }
    mock_make_request.install(authors_api).queue_responses(mock_response)

    result = await authors_api.find_duplicate_authors.fn(
        None, author_names=["John Smith"], match_by_orcid=False, match_by_dblp=True
    )

    assert len(result["groups"]) == 1
    assert "same_dblp" in result["groups"][0]["match_reasons"][0]


async def test_find_duplicate_authors_dblp_not_double_counted_with_orcid(mock_make_request):
    mock_response = {
        "total": 2,
        "data": [
            {
                "authorId": "1", "name": "John Smith", "citationCount": 1000,
                "externalIds": {"ORCID": "0000-0001-2345-6789", "DBLP": "homepages/s/JohnSmith"},
            },
            {
                "authorId": "2", "name": "J. Smith", "citationCount": 500,
                "externalIds": {"ORCID": "0000-0001-2345-6789", "DBLP": "homepages/s/JohnSmith"},
            },
        ],
    }
    mock_make_request.install(authors_api).queue_responses(mock_response)

    result = await authors_api.find_duplicate_authors.fn(None, author_names=["John Smith"])

    assert len(result["groups"]) == 1
    assert "same_orcid" in result["groups"][0]["match_reasons"][0]


async def test_consolidate_authors_requires_two_ids(mock_make_request):
    result = await authors_api.consolidate_authors.fn(None, author_ids=["single_id"])

    assert result["error"]["type"] == "validation"
    assert mock_make_request.calls == []


async def test_consolidate_authors_preview(mock_make_request):
    author1 = {
        "authorId": "1", "name": "John Smith", "citationCount": 1000, "paperCount": 30,
        "hIndex": 15, "affiliations": ["MIT"], "externalIds": {"ORCID": "0000-0001-2345-6789"},
    }
    author2 = {
        "authorId": "2", "name": "J. Smith", "citationCount": 500, "paperCount": 20,
        "hIndex": 10, "affiliations": ["Stanford"], "externalIds": {"ORCID": "0000-0001-2345-6789"},
    }
    mock_make_request.install(authors_api).queue_responses(author1, author2)

    result = await authors_api.consolidate_authors.fn(None, author_ids=["1", "2"], confirm_merge=False)

    assert result["merged_author"]["authorId"] == "1"
    assert result["merged_author"]["citationCount"] == 1500
    assert result["merged_author"]["paperCount"] == 50
    assert result["match_type"] == "orcid"
    assert result["confidence"] == 1.0
    assert result["is_preview"] is True


async def test_consolidate_authors_merges_affiliations(mock_make_request):
    author1 = {"authorId": "1", "name": "John Smith", "citationCount": 1000, "affiliations": ["MIT", "Google"]}
    author2 = {"authorId": "2", "name": "J. Smith", "citationCount": 500, "affiliations": ["Stanford", "MIT"]}
    mock_make_request.install(authors_api).queue_responses(author1, author2)

    result = await authors_api.consolidate_authors.fn(None, author_ids=["1", "2"])

    affiliations = result["merged_author"]["affiliations"]
    assert set(affiliations) == {"MIT", "Google", "Stanford"}
    assert affiliations.count("MIT") == 1


async def test_consolidate_authors_not_found(mock_make_request, mock_error_response):
    error = mock_error_response(status_code=404)
    mock_make_request.install(authors_api).queue_responses(error)

    result = await authors_api.consolidate_authors.fn(None, author_ids=["1", "2"])

    assert result["error"]["type"] == "validation"
    assert "not found" in result["error"]["message"].lower()


async def test_consolidate_authors_user_confirmed_match(mock_make_request):
    author1 = {"authorId": "1", "name": "John Smith", "citationCount": 1000, "externalIds": {"ORCID": "0000-0001-1111-1111"}}
    author2 = {"authorId": "2", "name": "J. Smith", "citationCount": 500, "externalIds": {"ORCID": "0000-0002-2222-2222"}}
    mock_make_request.install(authors_api).queue_responses(author1, author2)

    result = await authors_api.consolidate_authors.fn(None, author_ids=["1", "2"])

    assert result["match_type"] == "user_confirmed"
    assert result["confidence"] is None


async def test_consolidate_authors_dblp_match(mock_make_request):
    author1 = {
        "authorId": "1", "name": "John Smith", "citationCount": 1000, "paperCount": 30,
        "hIndex": 15, "externalIds": {"DBLP": "homepages/s/JohnSmith"},
    }
    author2 = {
        "authorId": "2", "name": "J. Smith", "citationCount": 500, "paperCount": 20,
        "hIndex": 10, "externalIds": {"DBLP": "homepages/s/JohnSmith"},
    }
    mock_make_request.install(authors_api).queue_responses(author1, author2)

    result = await authors_api.consolidate_authors.fn(None, author_ids=["1", "2"])

    assert result["match_type"] == "dblp"
    assert result["confidence"] == 0.95


async def test_consolidate_authors_external_ids_fallback(mock_make_request):
    author1 = {"authorId": "1", "name": "John Smith", "citationCount": 1000, "paperCount": 30, "externalIds": None}
    author2 = {
        "authorId": "2", "name": "J. Smith", "citationCount": 500, "paperCount": 20,
        "externalIds": {"ORCID": "0000-0001-2345-6789"},
    }
    mock_make_request.install(authors_api).queue_responses(author1, author2)

    result = await authors_api.consolidate_authors.fn(None, author_ids=["1", "2"])

    assert result["merged_author"]["externalIds"]["ORCID"] == "0000-0001-2345-6789"


async def test_find_duplicate_authors_empty_name_returns_dict(mock_make_request):
    # An empty name triggers synchronous request-object validation; the tool
    # must return a Dict error rather than let the exception escape.
    mock_make_request.install(authors_api)

    result = await authors_api.find_duplicate_authors.fn(None, author_names=["", "Jane Doe"])

    assert isinstance(result, dict)
    assert result["error"]["type"] == "validation"


async def test_consolidate_authors_empty_id_returns_dict(mock_make_request):
    mock_make_request.install(authors_api)

    result = await authors_api.consolidate_authors.fn(None, author_ids=["", "2"])

    assert isinstance(result, dict)
    assert result["error"]["type"] == "validation"


async def test_consolidate_authors_malformed_response_returns_dict(mock_make_request):
    # hIndex as a non-int makes Author(**response) raise; the tool must catch it
    # and return a Dict rather than let the exception escape.
    mock_make_request.install(authors_api).queue_responses(
        {"authorId": "1", "name": "X", "hIndex": "not-an-int"},
        {"authorId": "2", "name": "Y"},
    )

    result = await authors_api.consolidate_authors.fn(None, author_ids=["1", "2"])

    assert isinstance(result, dict)
    assert "error" in result
