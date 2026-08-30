from app.services.live_search import (
    TECH_ROLE_QUERIES,
    expand_search_queries,
)
from app.extraction import jsearch


def test_broad_tech_query_expands_into_role_families():
    assert expand_search_queries("  TECH jobs in USA ") == list(
        TECH_ROLE_QUERIES
    )


def test_specific_query_is_not_rewritten():
    query = "data engineer in Indianapolis"
    assert expand_search_queries(query) == [query]


def test_fetch_query_continues_from_cursor(monkeypatch):
    requested_parameters = []
    responses = iter(
        [
            {"data": {"jobs": [{"job_id": "2"}], "cursor": "cursor-3"}},
            {"data": {"jobs": [{"job_id": "3"}], "cursor": None}},
        ]
    )

    def fake_request_page(parameters):
        requested_parameters.append(parameters)
        return next(responses)

    monkeypatch.setattr(jsearch, "request_page", fake_request_page)

    jobs, pages, next_cursor = jsearch.fetch_query(
        "data engineer in USA",
        max_pages=2,
        start_cursor="cursor-2",
    )

    assert requested_parameters[0]["cursor"] == "cursor-2"
    assert requested_parameters[1]["cursor"] == "cursor-3"
    assert [job["job_id"] for job in jobs] == ["2", "3"]
    assert pages == 2
    assert next_cursor is None
