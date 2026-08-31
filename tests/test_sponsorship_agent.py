from app.agents.sponsorship_evidence import (
    SponsorshipEvidenceAgent,
    enrich_jobs_with_agent_reviews,
)
from app.api.main import determine_category


class FakeBedrockClient:
    def __init__(self, assessment=None, error=None):
        self.assessment = assessment
        self.error = error
        self.calls = []

    def converse(self, **request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return {
            "output": {
                "message": {
                    "content": [
                        {
                            "toolUse": {
                                "name": "record_sponsorship_assessment",
                                "input": self.assessment,
                            }
                        }
                    ]
                }
            },
            "usage": {
                "inputTokens": 250,
                "outputTokens": 50,
            },
        }


def make_agent(client):
    return SponsorshipEvidenceAgent(
        client=client,
        model_id="test-model",
        minimum_confidence=0.85,
    )


def test_agent_accepts_high_confidence_verbatim_evidence():
    description = (
        "We can provide employment sponsorship for qualified candidates. "
        "Experience with Python is required."
    )
    client = FakeBedrockClient(
        {
            "policy": "AVAILABLE",
            "confidence": 0.94,
            "evidence_quotes": [
                "We can provide employment sponsorship for qualified candidates."
            ],
            "rationale": "The posting expressly offers sponsorship.",
            "needs_human_review": False,
        }
    )

    review = make_agent(client).review(
        {
            "source_job_id": "job-1",
            "title": "Data Engineer",
            "company": "Example",
            "description": description,
        }
    )

    assert review["status"] == "COMPLETED"
    assert review["effective_policy"] == "AVAILABLE"
    assert review["requires_human_review"] is False
    assert review["input_tokens"] == 250
    assert review["output_tokens"] == 50
    assert client.calls[0]["toolConfig"]["toolChoice"] == {
        "tool": {"name": "record_sponsorship_assessment"}
    }
    evidence_schema = client.calls[0]["toolConfig"]["tools"][0][
        "toolSpec"
    ]["inputSchema"]["json"]["properties"]["evidence_quotes"]
    assert evidence_schema["maxItems"] == 1


def test_agent_prompt_disallows_weak_sponsorship_proxies():
    client = FakeBedrockClient(
        {
            "policy": "UNKNOWN",
            "confidence": 0.9,
            "evidence_quotes": [],
            "rationale": "E-Verify alone is not a sponsorship decision.",
            "needs_human_review": True,
        }
    )

    make_agent(client).review(
        {
            "source_job_id": "job-weak-proxy",
            "description": "We participate in E-Verify.",
        }
    )

    system_prompt = client.calls[0]["system"][0]["text"]
    assert "E-Verify" in system_prompt
    assert "security clearance" in system_prompt
    assert "exactly one strongest quotation" in system_prompt


def test_agent_rejects_evidence_not_found_in_posting():
    client = FakeBedrockClient(
        {
            "policy": "UNAVAILABLE",
            "confidence": 0.99,
            "evidence_quotes": ["We do not sponsor visas."],
            "rationale": "Sponsorship is denied.",
            "needs_human_review": False,
        }
    )

    review = make_agent(client).review(
        {
            "source_job_id": "job-2",
            "title": "Software Engineer",
            "company": "Example",
            "description": "Build reliable distributed systems.",
        }
    )

    assert review["status"] == "REJECTED"
    assert review["effective_policy"] == "UNKNOWN"
    assert review["error_code"] == "INVALID_EVIDENCE_QUOTE"


def test_agent_rejects_irrelevant_quote_even_when_it_exists():
    client = FakeBedrockClient(
        {
            "policy": "AVAILABLE",
            "confidence": 0.99,
            "evidence_quotes": ["Experience with Python is required."],
            "rationale": "The role is available.",
            "needs_human_review": False,
        }
    )

    review = make_agent(client).review(
        {
            "source_job_id": "job-irrelevant",
            "description": "Experience with Python is required.",
        }
    )

    assert review["status"] == "REJECTED"
    assert review["effective_policy"] == "UNKNOWN"


def test_agent_fails_closed_when_bedrock_is_unavailable():
    client = FakeBedrockClient(error=RuntimeError("service unavailable"))

    review = make_agent(client).review(
        {
            "source_job_id": "job-3",
            "description": "No sponsorship language is provided.",
        }
    )

    assert review["status"] == "ERROR"
    assert review["effective_policy"] == "UNKNOWN"
    assert review["requires_human_review"] is True


def test_agent_only_receives_deterministic_unknown_cases():
    client = FakeBedrockClient(
        {
            "policy": "UNKNOWN",
            "confidence": 0.4,
            "evidence_quotes": [],
            "rationale": "No conclusive evidence.",
            "needs_human_review": True,
        }
    )
    jobs = [
        {
            "source_job_id": "unknown",
            "current_policy": "UNKNOWN",
            "description": "No sponsorship language.",
        },
        {
            "source_job_id": "explicit-negative",
            "current_policy": "UNAVAILABLE",
            "description": "We cannot sponsor this role.",
        },
    ]

    enrich_jobs_with_agent_reviews(
        jobs,
        enabled=True,
        agent=make_agent(client),
    )

    assert len(client.calls) == 1
    assert "agent_review" in jobs[0]
    assert "agent_review" not in jobs[1]


def test_deterministic_policy_always_outranks_agent_policy():
    assert determine_category(
        current_policy="UNAVAILABLE",
        historical_support=True,
        agent_policy="AVAILABLE",
    ) == "CONFIRMED_UNAVAILABLE"

    assert determine_category(
        current_policy="UNKNOWN",
        historical_support=True,
        agent_policy="AVAILABLE",
    ) == "AGENT_LIKELY_AVAILABLE"
