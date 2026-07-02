from semantic_scholar.tracking_models import (
    Author,
    AuthorExternalIds,
    Paper,
    PublicationVenue,
)


def test_paper_defaults_are_all_optional():
    paper = Paper()
    assert paper.paperId is None
    assert paper.authors is None


def test_paper_accepts_extra_api_fields():
    paper = Paper(paperId="p1", title="T", isOpenAccess=True, s2FieldsOfStudy=[])
    assert paper.paperId == "p1"


def test_publication_venue_string_is_coerced_to_object():
    paper = Paper(paperId="p1", publicationVenue="c7f73dd6-8431-403d-8268-80d666abe1bc")
    assert isinstance(paper.publicationVenue, PublicationVenue)
    assert paper.publicationVenue.id == "c7f73dd6-8431-403d-8268-80d666abe1bc"


def test_author_external_ids_dblp_as_list():
    ids = AuthorExternalIds(DBLP=["homepages/s/JohnSmith"])
    assert ids.DBLP == ["homepages/s/JohnSmith"]


def test_paper_nests_authors():
    paper = Paper(paperId="p1", authors=[Author(authorId="a1", name="Jane Doe")])
    assert paper.authors[0].name == "Jane Doe"
