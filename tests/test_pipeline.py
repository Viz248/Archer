import httpx
import pytest
from pydantic import ValidationError

from app.pipeline.engine import run_pipeline
from app.pipeline import engine
from app.pipeline import llm
from app.models import Architecture, Component, Requirement, TraceLink


def test_pipeline_generates_traceable_architecture():
    r = run_pipeline("Users shall register and log in.\nUsers shall place orders and pay online.\nThe system shall send email notifications.")
    assert len(r.requirements) >= 3
    assert len(r.architecture.components) >= 2
    assert len(r.trace_links) >= 3
    assert "sequence" in r.uml
    assert "# AI Assisted" in r.report_markdown


def test_ambiguous_requirement_is_flagged():
    r = run_pipeline("Make it fast.")
    assert r.requirements[0].type == "ambiguous"
    assert r.warnings


def test_pipeline_exposes_partial_availability_and_recommended_patterns():
    result = run_pipeline("The system shall support high availability.")

    assert result.requirement_assessments[0].status == "partially_satisfied"
    assert any(f.code == "availability_mechanism_unspecified" for f in result.evaluation_findings)
    availability_finding = next(
        finding for finding in result.evaluation_findings
        if finding.code == "availability_mechanism_unspecified"
    )
    assert result.report_markdown.count(availability_finding.message) == 1
    assert result.architecture.recommended_patterns
    assert "Recommended, Not Yet Applied" in result.report_markdown
    assert "### Recommended, Not Yet Applied\n\n- Strategy" in result.report_markdown
    assert "- Strategy" not in result.report_markdown.split("## 5. Applied Design Patterns", 1)[1].split("### Recommended, Not Yet Applied", 1)[0]
    assert "Actionable Findings" in result.report_markdown


def test_live_pipeline_preserves_semantic_requirement_assessments(monkeypatch):
    requirement = Requirement(
        id="REQ-001", text="Users can place orders.", type="functional", confidence=0.9
    )
    component = Component(
        id="COMP-001", name="Order Service", responsibility="Creates orders.", requirements=["REQ-001"]
    )
    architecture = Architecture(
        style="Layered", components=[component], relationships=[], patterns=["Layered Architecture"]
    )
    trace = [TraceLink(
        requirement_id="REQ-001",
        architectural_element="Order Service",
        decision="Use Order Service",
        rationale="Creates orders.",
        confidence=0.9,
    )]
    semantic_assessment = llm.LLMRequirementAssessment(
        requirement_id="REQ-001",
        status="partially_satisfied",
        evidence="Order creation is modeled.",
        gaps=["Order cancellation is not described."],
    )
    monkeypatch.setattr(engine, "is_enabled", lambda: True)
    monkeypatch.setattr(
        engine,
        "run_llm_pipeline",
        lambda _text: ([requirement], architecture, trace, [], ["Groq reflection"], [semantic_assessment]),
    )

    result = run_pipeline("Users can place orders.")

    assert result.mode == "live-llm"
    assert result.requirement_assessments[0].status == "partially_satisfied"
    assert "Order cancellation is not described." in result.requirement_assessments[0].gaps
    assert any(f.code == "requirement_partial" for f in result.evaluation_findings)


def test_llm_synthesis_uses_explicit_output_token_budget(monkeypatch):
    seen = {}

    class FakeResponse:
        output_parsed = llm.ArchitectureSynthesisResult(
            style="Layered",
            components=[llm.LLMComponent(
                name="Order Service",
                responsibility="Processes orders",
                requirement_ids=["REQ-001"],
                technologies=["REST"]
            )],
            relationships=[],
            patterns=["layered architecture"],
            recommended_patterns=[],
            architectural_summary="A simple layered architecture for order processing.",
        )

    class FakeResponses:
        def parse(self, **kwargs):
            seen.update(kwargs)
            return FakeResponse()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    reqs = [Requirement(id="REQ-001", text="Users can place orders.", type="functional", confidence=1.0)]
    components = [
        Component(
            id="COMP-001",
            name="Order Service",
            responsibility="Processes orders",
            requirements=["REQ-001"],
            technologies=["REST"],
        )
    ]

    result = llm._synthesize(reqs, components)

    assert result.style == "Layered"
    assert seen["max_output_tokens"] >= 4000
    assert all(f'"{field}"' in seen["input"] for field in (
        "style", "components", "relationships", "patterns", "recommended_patterns", "architectural_summary"
    ))


@pytest.mark.parametrize(
    ("pattern_label", "recommended_name"),
    [
        ("Recommended: Circuit Breaker", "Circuit Breaker"),
        ("Circuit Breaker (recommended)", "Circuit Breaker"),
        ("Circuit Breaker - recommended", "Circuit Breaker"),
    ],
)
def test_synthesis_separates_prefixed_recommendations(monkeypatch, pattern_label, recommended_name):
    result_payload = llm.ArchitectureSynthesisResult(
        style="Layered",
        components=[],
        relationships=[],
        patterns=["Layered Architecture", pattern_label],
        recommended_patterns=["Circuit Breaker"],
        architectural_summary="A layered design.",
    )

    class FakeResponses:
        def parse(self, **kwargs):
            return type("FakeResponse", (), {"output_parsed": result_payload})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    reqs = [Requirement(id="REQ-001", text="Users can place orders.", type="functional", confidence=1.0)]

    result = llm._synthesize(reqs, [])

    assert result.patterns == ["Layered Architecture"]
    assert result.recommended_patterns == [recommended_name]


@pytest.mark.parametrize(
    ("result_model", "required_fields"),
    [
        (llm.RequirementParseResult, {"requirements"}),
        (llm.ComponentExtractionResult, {"components"}),
        (llm.ArchitectureSynthesisResult, {
            "style", "components", "relationships", "patterns", "recommended_patterns", "architectural_summary"
        }),
        (llm.RationaleResult, {"trace_links", "requirement_assessments", "warnings", "review_notes"}),
    ],
)
def test_stage_models_reject_missing_required_fields(result_model, required_fields):
    with pytest.raises(ValidationError) as error:
        result_model.model_validate({})

    missing_fields = {item["loc"][0] for item in error.value.errors()}
    assert missing_fields == required_fields


def test_rationale_schema_rejects_missing_review_notes():
    with pytest.raises(ValidationError) as error:
        llm.RationaleResult.model_validate({"trace_links": [], "warnings": []})

    assert any(item["loc"] == ("review_notes",) for item in error.value.errors())


@pytest.mark.parametrize(
    ("model", "payload", "missing_fields"),
    [
        (llm.LLMRequirement, {"id": "REQ-001"}, {"text", "type", "confidence"}),
        (llm.LLMComponent, {"name": "Order Service"}, {"responsibility", "requirement_ids"}),
        (llm.LLMRelationship, {"source": "A"}, {"target", "kind", "rationale"}),
        (llm.LLMTraceLink, {"requirement_id": "REQ-001"}, {
            "architectural_element", "decision", "rationale", "confidence"
        }),
        (llm.LLMRequirementAssessment, {"requirement_id": "REQ-001"}, {
            "status", "evidence", "gaps"
        }),
    ],
)
def test_nested_stage_models_reject_missing_required_fields(model, payload, missing_fields):
    with pytest.raises(ValidationError) as error:
        model.model_validate(payload)

    assert {item["loc"][0] for item in error.value.errors()} == missing_fields


@pytest.mark.parametrize(
    ("result_model", "required_fields"),
    [
        (llm.RequirementParseResult, ("requirements", "id", "text", "type", "confidence", "ambiguity_reason")),
        (llm.ComponentExtractionResult, ("components", "name", "responsibility", "requirement_ids", "technologies")),
        (llm.ArchitectureSynthesisResult, (
            "style", "components", "relationships", "source", "target", "kind", "rationale",
            "patterns", "recommended_patterns", "architectural_summary",
        )),
        (llm.RationaleResult, (
            "trace_links", "requirement_id", "architectural_element", "decision", "rationale",
            "confidence", "requirement_assessments", "status", "evidence", "gaps", "warnings", "review_notes",
        )),
    ],
)
def test_stage_prompt_contracts_name_all_schema_fields(result_model, required_fields):
    contract = llm._with_output_contract("stage prompt", result_model)

    assert all(f'"{field}"' in contract for field in required_fields)
    if result_model is llm.RationaleResult:
        assert '"warnings":[]' in contract
        assert '"review_notes":[]' in contract
        assert "never omit review_notes" in contract


@pytest.mark.parametrize(
    ("headers", "expected_wait"),
    [({"retry-after": "2"}, 2.0), ({"retry-after-ms": "2500"}, 2.5)],
)
def test_groq_rate_limit_retry_honors_retry_after(monkeypatch, headers, expected_wait):
    waits = []
    response_value = object()

    class FakeResponses:
        calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                response = httpx.Response(
                    429,
                    headers=headers,
                    request=httpx.Request("POST", "https://api.groq.com/openai/v1/responses"),
                )
                raise llm.RateLimitError("rate limited", response=response, body={})
            return response_value

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_provider", lambda: "Groq")
    monkeypatch.setattr(llm.time, "sleep", waits.append)

    result = llm._groq_responses_parse(FakeClient(), model="test-model")

    assert result is response_value
    assert FakeClient.responses.calls == 2
    assert waits == [expected_wait]


def test_groq_rate_limit_retry_is_bounded_with_exponential_backoff(monkeypatch):
    waits = []

    class FakeResponses:
        calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            response = httpx.Response(
                429,
                request=httpx.Request("POST", "https://api.groq.com/openai/v1/responses"),
            )
            raise llm.RateLimitError("rate limited", response=response, body={})

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_provider", lambda: "Groq")
    monkeypatch.setattr(llm.time, "sleep", waits.append)

    with pytest.raises(llm.RateLimitError):
        llm._groq_responses_parse(FakeClient(), model="test-model")

    assert FakeClient.responses.calls == llm._MAX_GROQ_RATE_LIMIT_RETRIES + 1
    assert waits == [1.0, 2.0, 4.0]


def test_ollama_qwen3_uses_chat_completions_and_parses_json(monkeypatch):
    seen = {}

    class FakeMessage:
        def __init__(self, content, reasoning=None):
            self.content = content
            self.reasoning = reasoning
            self.reasoning_content = None

    class FakeChoice:
        def __init__(self, content, reasoning=None):
            self.message = FakeMessage(content, reasoning)

    class FakeChatCompletion:
        def __init__(self, content, reasoning=None):
            self.choices = [FakeChoice(content, reasoning)]

    class FakeCompletions:
        def create(self, **kwargs):
            seen.update(kwargs)
            return FakeChatCompletion(
                '{"atomic_requirements":[{"id":"REQ-001","text":"Users can register.","type":"functional","confidence":1.0,"ambiguity_reason":""}]}'
            )

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")

    result = llm._parse("Users can register.")

    assert result.requirements[0].id == "REQ-001"
    assert result.requirements[0].text == "Users can register."
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["reasoning_effort"] == "none"
    assert seen["max_tokens"] == 2000


def test_ollama_qwen3_retry_handles_markdown_and_reasoning_variants(monkeypatch):
    payloads = [
        '```json\n{"components": ["Authentication Service", "Order Service"]}\n```',
        '{"components": [{"name": "Authentication Service", "responsibility": "Login and access control", "requirement_ids": ["REQ-001"], "technologies": ["JWT"]}], "relationships": {"Authentication Service": {"Order Service": "Handles authentication before order creation"}}, "patterns": "API Gateway", "recommended_patterns": [], "architectural_summary": "A layered flow."}',
    ]
    calls = []

    class FakeMessage:
        def __init__(self, content, reasoning=None):
            self.content = content
            self.reasoning = reasoning
            self.reasoning_content = None

    class FakeChoice:
        def __init__(self, content, reasoning=None):
            self.message = FakeMessage(content, reasoning)

    class FakeChatCompletion:
        def __init__(self, content, reasoning=None):
            self.choices = [FakeChoice(content, reasoning)]

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            content = payloads.pop(0)
            if content.startswith('```'):
                return FakeChatCompletion(content)
            return FakeChatCompletion(content)

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:8b")

    reqs = [Requirement(id="REQ-001", text="Users can register.", type="functional", confidence=1.0)]
    result = llm._ollama_structured_call(llm.ArchitectureSynthesisResult, "Synthesize a system.", max_output_tokens=3000)

    assert result.style in {"Layered", "Architecture synthesized from the provided requirements."}
    assert result.components[0].name in {"Authentication Service", "Component-01"}
    assert result.patterns[0] == "API Gateway" or result.patterns == ["API Gateway"]
    assert calls
