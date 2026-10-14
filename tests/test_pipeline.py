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
    assert availability_finding.finding_id in result.requirement_assessments[0].finding_ids
    assert f"| REQ-001 | partially_satisfied |" in result.report_markdown
    assert f"| {availability_finding.finding_id} | warning |" in result.report_markdown
    assert all(gap not in result.report_markdown for gap in result.requirement_assessments[0].gaps)
    finding_warning = next(
        warning for warning in result.warnings
        if warning.startswith(f"[{availability_finding.finding_id}]")
    )
    assert finding_warning not in result.report_markdown
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


def test_live_pipeline_downgrades_satisfied_availability_assessment(monkeypatch):
    requirement = Requirement(
        id="REQ-001",
        text="The system shall support high availability.",
        type="non_functional",
        confidence=0.9,
    )
    component = Component(
        id="COMP-001",
        name="High Availability Infrastructure",
        responsibility="Coordinates system operations.",
        requirements=["REQ-001"],
    )
    architecture = Architecture(
        style="Layered",
        components=[component],
        relationships=[],
        patterns=["Layered Architecture"],
    )
    trace = [TraceLink(
        requirement_id="REQ-001",
        architectural_element="High Availability Infrastructure",
        decision="Use High Availability Infrastructure",
        rationale="Coordinates system operations.",
        confidence=0.9,
    )]
    semantic_assessment = llm.LLMRequirementAssessment(
        requirement_id="REQ-001",
        status="satisfied",
        evidence="High Availability Infrastructure coordinates system operations.",
        gaps=[],
    )
    monkeypatch.setattr(engine, "is_enabled", lambda: True)
    monkeypatch.setattr(
        engine,
        "run_llm_pipeline",
        lambda _text: ([requirement], architecture, trace, [], ["Groq reflection"], [semantic_assessment]),
    )

    result = run_pipeline("The system shall support high availability.")

    assert result.mode == "live-llm"
    assert result.requirement_assessments[0].status == "partially_satisfied"
    assert any(f.code == "availability_mechanism_unspecified" for f in result.evaluation_findings)
    availability_finding = next(
        f for f in result.evaluation_findings if f.code == "availability_mechanism_unspecified"
    )
    assert availability_finding.finding_id in result.requirement_assessments[0].finding_ids
    assert any(
        "No concrete availability mechanism is described" in gap
        for gap in result.requirement_assessments[0].gaps
    )


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
    assert all(field in seen["input"] for field in (
        "style:string", "components:list", "relationships:list", "patterns:list[string]",
        "recommended_patterns:list[string]", "architectural_summary:string",
    ))
    assert "Do not provide chain-of-thought" in seen["instructions"]
    assert "Copy each pair exactly" in seen["input"]


def test_synthesis_retries_once_when_groq_rejects_prose_output(monkeypatch):
    architecture = llm.ArchitectureSynthesisResult(
        style="Layered",
        components=[],
        relationships=[],
        patterns=[],
        recommended_patterns=[],
        architectural_summary="A layered architecture.",
    )
    calls = []

    class ProviderParseError(Exception):
        status_code = 400
        body = {
            "error": {
                "code": "output_parse_failed",
                "message": 'I will reason through this first. Example: {"style":"Layered"}',
            }
        }

    class FakeResponses:
        def parse(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ProviderParseError("output_parse_failed")
            return type("FakeResponse", (), {"output_parsed": architecture})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_provider", lambda: "Groq")

    response = llm._groq_responses_parse(
        FakeClient(),
        stage="architecture synthesis",
        model="configured-model",
        instructions="Return structured architecture only.",
        input="Synthesize the candidates.",
        text_format=llm.ArchitectureSynthesisResult,
        max_output_tokens=6000,
    )

    assert response.output_parsed is architecture
    assert len(calls) == 2
    assert calls[1]["input"] != calls[0]["input"]
    assert "Return only the structured object" in calls[1]["input"]
    assert calls[0]["text_format"] is llm.ArchitectureSynthesisResult
    assert calls[1]["text_format"] is llm.ArchitectureSynthesisResult


def test_permanent_groq_schema_error_is_not_retried(monkeypatch):
    class ProviderSchemaError(Exception):
        status_code = 400
        body = {"error": {"code": "invalid_json_schema", "message": "Schema is unsupported."}}

    class FakeResponses:
        calls = 0

        def parse(self, **kwargs):
            self.calls += 1
            raise ProviderSchemaError("invalid_json_schema")

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_provider", lambda: "Groq")

    with pytest.raises(RuntimeError, match="architecture synthesis"):
        llm._groq_responses_parse(
            FakeClient(), stage="architecture synthesis", input="prompt", text_format=llm.ArchitectureSynthesisResult
        )

    assert FakeClient.responses.calls == 1


def test_component_extraction_rejects_unknown_requirement_ids(monkeypatch):
    output = llm.ComponentExtractionResult(components=[llm.LLMComponent(
        name="Order Service",
        responsibility="Creates orders.",
        requirement_ids=["REQ-999"],
        technologies=[],
    )])

    class FakeResponses:
        def parse(self, **kwargs):
            return type("FakeResponse", (), {"output_parsed": output})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    monkeypatch.setattr(llm, "_provider", lambda: "Groq")
    monkeypatch.setattr(llm, "_is_ollama", lambda: False)
    reqs = [Requirement(id="REQ-001", text="Users can place orders.", type="functional", confidence=0.9)]

    with pytest.raises(ValueError, match="REQ-999"):
        llm._components(reqs)


def test_architecture_synthesis_cannot_reassign_component_requirement_ids(monkeypatch):
    output = llm.ArchitectureSynthesisResult(
        style="Layered",
        components=[llm.LLMComponent(
            name="Order Service",
            responsibility="Creates orders.",
            requirement_ids=["REQ-002"],
            technologies=[],
        )],
        relationships=[],
        patterns=[],
        recommended_patterns=[],
        architectural_summary="A layered design.",
    )

    class FakeResponses:
        def parse(self, **kwargs):
            return type("FakeResponse", (), {"output_parsed": output})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    monkeypatch.setattr(llm, "_provider", lambda: "Groq")
    monkeypatch.setattr(llm, "_is_ollama", lambda: False)
    reqs = [Requirement(id="REQ-001", text="Users can place orders.", type="functional", confidence=0.9)]
    candidates = [Component(
        id="COMP-001", name="Order Service", responsibility="Creates orders.", requirements=["REQ-001"]
    )]

    with pytest.raises(ValueError, match="must preserve candidate requirement IDs"):
        llm._synthesize(reqs, candidates)


def test_architecture_synthesis_cannot_reorder_candidate_requirement_ids():
    candidates = [Component(
        id="COMP-001", name="Order Service", responsibility="Creates orders.",
        requirements=["REQ-001", "REQ-002"],
    )]
    synthesized = [llm.LLMComponent(
        name="Order Service", responsibility="Creates orders.",
        requirement_ids=["REQ-002", "REQ-001"], technologies=[],
    )]

    with pytest.raises(ValueError, match="must preserve candidate requirement IDs"):
        llm._validate_synthesis_component_mappings(candidates, synthesized)


def test_reflection_rejects_unknown_requirement_ids(monkeypatch):
    output = llm.RationaleResult(
        trace_links=[llm.LLMTraceLink(
            requirement_id="REQ-999", architectural_element="Order Service", decision="Create service",
            rationale="It creates orders.", confidence=0.9,
        )],
        requirement_assessments=[llm.LLMRequirementAssessment(
            requirement_id="REQ-001", status="satisfied", evidence="The service creates orders.", gaps=[]
        )],
        warnings=[],
        review_notes=[],
    )

    class FakeResponses:
        def parse(self, **kwargs):
            return type("FakeResponse", (), {"output_parsed": output})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    monkeypatch.setattr(llm, "_provider", lambda: "Groq")
    monkeypatch.setattr(llm, "_is_ollama", lambda: False)
    reqs = [Requirement(id="REQ-001", text="Users can place orders.", type="functional", confidence=0.9)]
    arch = Architecture(
        style="Layered",
        components=[Component("COMP-001", "Order Service", "Creates orders.", ["REQ-001"])],
        relationships=[],
        patterns=[],
    )

    with pytest.raises(ValueError, match="REQ-999"):
        llm._rationale(reqs, arch)


def test_structured_outputs_keep_missing_schema_fields_invalid():
    with pytest.raises(ValidationError) as error:
        llm.ArchitectureSynthesisResult.model_validate({
            "style": "Layered",
            "components": [],
            "relationships": [],
            "patterns": [],
            "architectural_summary": "A design.",
        })

    assert any(item["loc"] == ("recommended_patterns",) for item in error.value.errors())


def test_valid_structured_outputs_continue_through_full_llm_pipeline(monkeypatch):
    requirement = llm.LLMRequirement(
        id="REQ-001", text="Users can place orders.", type="functional", confidence=0.9
    )
    parsed_by_schema = {
        llm.RequirementParseResult: llm.RequirementParseResult(requirements=[requirement]),
        llm.ComponentExtractionResult: llm.ComponentExtractionResult(components=[llm.LLMComponent(
            name="Order Service", responsibility="Creates orders.", requirement_ids=["REQ-001"], technologies=[]
        )]),
        llm.ArchitectureSynthesisResult: llm.ArchitectureSynthesisResult(
            style="Layered",
            components=[llm.LLMComponent(
                name="Order Service", responsibility="Creates orders.", requirement_ids=["REQ-001"], technologies=[]
            )],
            relationships=[], patterns=[], recommended_patterns=[], architectural_summary="Orders are handled in a layer.",
        ),
        llm.RationaleResult: llm.RationaleResult(
            trace_links=[llm.LLMTraceLink(
                requirement_id="REQ-001", architectural_element="Order Service", decision="Create service",
                rationale="It creates orders.", confidence=0.9,
            )],
            requirement_assessments=[llm.LLMRequirementAssessment(
                requirement_id="REQ-001", status="satisfied", evidence="The service creates orders.", gaps=[]
            )],
            warnings=[], review_notes=[],
        ),
    }

    class FakeResponses:
        def parse(self, **kwargs):
            return type("FakeResponse", (), {"output_parsed": parsed_by_schema[kwargs["text_format"]]})()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr(llm, "_client", lambda: FakeClient())
    monkeypatch.setattr(llm, "_provider", lambda: "Groq")
    monkeypatch.setattr(llm, "_is_ollama", lambda: False)

    reqs, architecture, trace, warnings, stages, assessments = llm.run_llm_pipeline("Users can place orders.")

    assert [item.id for item in reqs] == ["REQ-001"]
    assert architecture.components[0].requirements == ["REQ-001"]
    assert trace[0].requirement_id == "REQ-001"
    assert assessments[0].requirement_id == "REQ-001"
    assert warnings == []
    assert len(stages) == 4


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

    if result_model is llm.ArchitectureSynthesisResult:
        assert all(field in contract for field in required_fields)
    else:
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
