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
