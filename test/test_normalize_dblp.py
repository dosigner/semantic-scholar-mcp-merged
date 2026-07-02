import semantic_scholar.api.authors as authors_api


def test_normalize_dblp_variants():
    assert authors_api._normalize_dblp(None) is None
    assert authors_api._normalize_dblp([]) is None
    assert authors_api._normalize_dblp("x") == "x"
    assert authors_api._normalize_dblp(["a", "b"]) == "a"
