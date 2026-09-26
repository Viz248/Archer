"""Model-backed pipeline stages for Req2Arch.

The demo uses the OpenAI Responses API with Pydantic structured outputs. If no
API key is configured, the caller can fall back to the deterministic pipeline.
"""
from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel, Field

from app.models import Architecture, Component, Relationship, Requirement, TraceLink

try:
    from openai import OpenAI, pydantic_function_tool
except ImportError:  # pragma: no cover - handled by runtime dependency install
    OpenAI = None
    pydantic_function_tool = None


class LLMRequirement(BaseModel):
    id: str
    text: str
    type: Literal["functional", "non_functional", "ambiguous"]
    confidence: float = Field(ge=0, le=1)
    ambiguity_reason: str = ""


class RequirementParseResult(BaseModel):
    requirements: list[LLMRequirement]


class LLMComponent(BaseModel):
    name: str
    responsibility: str
    requirement_ids: list[str]
    technologies: list[str] = []


class ComponentExtractionResult(BaseModel):
    components: list[LLMComponent]


class LLMRelationship(BaseModel):
    source: str
    target: str
    kind: str
    rationale: str


class ArchitectureSynthesisResult(BaseModel):
    style: str
    components: list[LLMComponent]
    relationships: list[LLMRelationship]
    patterns: list[str]
    architectural_summary: str


class LLMTraceLink(BaseModel):
    requirement_id: str
    architectural_element: str
    decision: str
    rationale: str
    confidence: float = Field(ge=0, le=1)


class RationaleResult(BaseModel):
    trace_links: list[LLMTraceLink]
    warnings: list[str]
    review_notes: list[str]


class PatternRecommendation(BaseModel):
    pattern: str
    reason: str


SYSTEM_BASE = """You are an experienced software architect assisting a requirements-to-architecture
synthesis system. Be conservative: never invent a requirement that is not present.
Prefer high-level architecture components over implementation-level classes.
Preserve requirement IDs exactly. Produce concise, reviewable reasoning. The goal is
an explainable architecture, not a generic template. Different requirement sets should
produce materially different architectures when their capabilities or quality attributes differ.
"""


def is_enabled() -> bool:
    return bool(os.getenv("LLM_API_KEY", "").strip()) and OpenAI is not None


def _client() -> OpenAI:
    if not is_enabled():
        raise RuntimeError("LLM is not configured. Set LLM_API_KEY and install the openai package.")
    kwargs = {"api_key": os.environ["LLM_API_KEY"]}
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _model() -> str:
    return os.getenv("LLM_MODEL", "gpt-5.6-terra")


def _provider() -> str:
    base_url = os.getenv("LLM_BASE_URL", "").lower()
    if "groq" in base_url:
        return "Groq"
    if "azure" in base_url:
        return "Azure OpenAI"
    if "openai" in base_url:
        return "OpenAI"
    return "OpenAI-compatible"


def _response_kwargs(*, text_format: type[BaseModel], max_output_tokens: int) -> dict:
    return {
        "text_format": text_format,
        "max_output_tokens": max_output_tokens,
    }


def _parse(text: str) -> RequirementParseResult:
    client = _client()
    prompt = f"""Parse the following software requirements into atomic requirements.
Classify each as functional, non_functional, or ambiguous. Mark something ambiguous
when the wording is genuinely underspecified (not merely because it is short).
Assign stable IDs REQ-001, REQ-002, ... in input order.

REQUIREMENTS:\n{text}"""
    response = client.responses.parse(
        model=_model(),
        instructions=SYSTEM_BASE,
        input=prompt,
        **_response_kwargs(text_format=RequirementParseResult, max_output_tokens=2000),
    )
    if not response.output_parsed:
        raise RuntimeError("Model returned no structured requirement output.")
    return response.output_parsed


def _components(reqs: list[Requirement]) -> ComponentExtractionResult:
    client = _client()
    payload = "\n".join(f"{r.id} [{r.type}] {r.text}" for r in reqs)
    prompt = f"""Extract the major architectural components needed by these requirements.
Deduplicate overlapping responsibilities. Every functional requirement should map to
one or more components when appropriate; non-functional requirements may be represented
as cross-cutting infrastructure or constraints. Do not create components merely because
a keyword appears. Include likely technologies only when they are justified by the requirements.

REQUIREMENTS:\n{payload}"""
    response = client.responses.parse(
        model=_model(),
        instructions=SYSTEM_BASE,
        input=prompt,
        **_response_kwargs(text_format=ComponentExtractionResult, max_output_tokens=3000),
    )
    if not response.output_parsed:
        raise RuntimeError("Model returned no structured component output.")
    return response.output_parsed


def _recommend_pattern(pattern: str, context: str) -> PatternRecommendation:
    """Local tool implementation used by the synthesis stage."""
    reasons = {
        "layered architecture": "Separates presentation, orchestration, domain, and persistence concerns.",
        "pipeline": "Makes sequential transformation stages independently inspectable and rerunnable.",
        "strategy": "Allows alternative synthesis or policy algorithms to be swapped behind a common interface.",
        "facade": "Provides a simple API entry point over the multi-stage pipeline.",
        "repository": "Decouples domain objects from persistence and improves testability.",
        "observer": "Supports incremental progress updates as pipeline stages complete.",
        "chain of responsibility": "Supports successive validation and clarification checks.",
        "factory method": "Centralizes validated construction of architecture domain objects.",
    }
    key = pattern.lower()
    return PatternRecommendation(pattern=pattern, reason=reasons.get(key, f"Fits the architectural context: {context[:180]}"))


def _component_requirement_ids(component: Component | LLMComponent) -> list[str]:
    if hasattr(component, "requirement_ids"):
        return list(getattr(component, "requirement_ids"))
    if hasattr(component, "requirements"):
        return list(getattr(component, "requirements"))
    return []


def _synthesize(reqs: list[Requirement], components: list[Component]) -> ArchitectureSynthesisResult:
    client = _client()
    req_text = "\n".join(f"{r.id}: {r.text}" for r in reqs)
    comp_text = "\n".join(
        f"{c.name}: {c.responsibility} (requirements: {', '.join(_component_requirement_ids(c))})" for c in components
    )
    prompt = f"""Synthesize a high-level architecture from the parsed requirements and extracted components.
Choose the architecture style based on the actual requirements. Define only relationships that
are supported by the requirements or obvious architectural structure. Explain each relationship.
Select a small set of established patterns that are genuinely useful here. Return the complete
component list so it can be validated downstream.

REQUIREMENTS:\n{req_text}\n\nCANDIDATE COMPONENTS:\n{comp_text}"""

    response = client.responses.parse(
        model=_model(),
        instructions=SYSTEM_BASE,
        input=prompt,
        **_response_kwargs(text_format=ArchitectureSynthesisResult, max_output_tokens=6000),
    )
    if not response.output_parsed:
        raise RuntimeError("Model returned no structured architecture output.")
    result = response.output_parsed
    # Tool-use stage: run a deterministic local architecture-pattern recommender on
    # the model-selected patterns. This makes pattern rationale a separate, testable
    # tool stage rather than burying everything in one prompt.
    for pattern in result.patterns:
        _recommend_pattern(pattern, result.architectural_summary)
    return result


def _rationale(reqs: list[Requirement], arch: Architecture) -> RationaleResult:
    client = _client()
    req_text = "\n".join(f"{r.id}: {r.text}" for r in reqs)
    comp_text = "\n".join(f"- {c.name}: {c.responsibility} [{', '.join(c.requirements)}]" for c in arch.components)
    rel_text = "\n".join(f"- {x.source} -> {x.target} ({x.kind}): {x.rationale}" for x in arch.relationships)
    prompt = f"""Act as the reflection/evaluator stage. Review the proposed architecture against the
requirements. Create one or more trace links for every requirement. Each trace link must explain
why the mapped architectural element exists. Identify concrete gaps, contradictions, unsupported
assumptions, or ambiguous requirements in warnings. Review the architecture for consistency and
requirement coverage; do not claim it is correct merely because it is plausible.

REQUIREMENTS:\n{req_text}\n\nARCHITECTURE STYLE: {arch.style}\nCOMPONENTS:\n{comp_text}\n\nRELATIONSHIPS:\n{rel_text}\n\nPATTERNS: {', '.join(arch.patterns)}"""
    response = client.responses.parse(
        model=_model(),
        instructions=SYSTEM_BASE,
        input=prompt,
        **_response_kwargs(text_format=RationaleResult, max_output_tokens=4000),
    )
    if not response.output_parsed:
        raise RuntimeError("Model returned no structured rationale output.")
    return response.output_parsed


def run_llm_pipeline(text: str) -> tuple[list[Requirement], Architecture, list[TraceLink], list[str], list[str]]:
    parsed = _parse(text)
    reqs = [Requirement(id=r.id, text=r.text, type=r.type, confidence=r.confidence) for r in parsed.requirements]

    extracted = _components(reqs)
    comps = [
        Component(
            id=f"COMP-{i:03d}",
            name=c.name,
            responsibility=c.responsibility,
            requirements=sorted(set(c.requirement_ids)),
            technologies=sorted(set(c.technologies)),
        )
        for i, c in enumerate(extracted.components, 1)
    ]

    synthesized = _synthesize(reqs, comps)
    # Use the synthesizer's complete list while preserving generated IDs.
    final_components = [
        Component(
            id=f"COMP-{i:03d}",
            name=c.name,
            responsibility=c.responsibility,
            requirements=sorted(set(c.requirement_ids)),
            technologies=sorted(set(c.technologies)),
        )
        for i, c in enumerate(synthesized.components, 1)
    ]
    arch = Architecture(
        style=synthesized.style,
        components=final_components,
        relationships=[Relationship(source=x.source, target=x.target, kind=x.kind, rationale=x.rationale) for x in synthesized.relationships],
        patterns=synthesized.patterns,
    )

    reviewed = _rationale(reqs, arch)
    trace = [TraceLink(
        requirement_id=x.requirement_id,
        architectural_element=x.architectural_element,
        decision=x.decision,
        rationale=x.rationale,
        confidence=x.confidence,
    ) for x in reviewed.trace_links]
    warnings = reviewed.warnings + reviewed.review_notes
    return reqs, arch, trace, warnings, [
        "LLM requirement parsing (structured output)",
        "LLM component extraction (structured output)",
        "LLM architecture synthesis + local pattern tool",
        "LLM reflection/evaluator-optimizer pass",
    ]
