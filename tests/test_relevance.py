from app.pipeline.relevance import evaluate_job_relevance


def test_data_engineer_is_relevant():
    relevant, _ = evaluate_job_relevance("Senior Data Engineer")
    assert relevant is True


def test_data_center_engineer_is_rejected():
    relevant, reason = evaluate_job_relevance("Data Center Engineer - Cabling")
    assert relevant is False
    assert reason == "REJECTED_DATA_CENTER"
