from app.pipeline.engine import run_pipeline
from app.pipeline import llm
from app.models import Component, Requirement


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
        '{"components": [{"name": "Authentication Service", "responsibility": "Login and access control", "requirement_ids": ["REQ-001"], "technologies": ["JWT"]}], "relationships": {"Authentication Service": {"Order Service": "Handles authentication before order creation"}}, "patterns": "API Gateway", "architectural_summary": "A layered flow."}',
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
