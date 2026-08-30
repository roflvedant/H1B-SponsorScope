from app.services.live_search import (
    TECH_ROLE_QUERIES,
    expand_search_queries,
)


def test_broad_tech_query_expands_into_role_families():
    assert expand_search_queries("  TECH jobs in USA ") == list(
        TECH_ROLE_QUERIES
    )


def test_specific_query_is_not_rewritten():
    query = "data engineer in Indianapolis"
    assert expand_search_queries(query) == [query]
