"""Model-backed pipeline stages for Req2Arch.

The demo uses the OpenAI Responses API with Pydantic structured outputs. If no
API key is configured, the caller can fall back to the deterministic pipeline.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import Architecture, Component, Relationship, Requirement, TraceLink

try:
    from openai import OpenAI, RateLimitError, pydantic_function_tool
except ImportError:  # pragma: no cover - handled by runtime dependency install
    OpenAI = None
    RateLimitError = None
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
    enabled = os.getenv("LLM_ENABLED", "").strip().lower()
    if enabled in {"1", "true", "yes", "on"}:
        return bool(os.getenv("LLM_API_KEY", "").strip()) and OpenAI is not None
    return bool(os.getenv("LLM_API_KEY", "").strip()) and OpenAI is not None


def _client() -> OpenAI:
    if not is_enabled():
        raise RuntimeError("LLM is not configured. Set LLM_API_KEY and install the openai package.")
    kwargs = {"api_key": os.environ["LLM_API_KEY"]}
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    if base_url:
        kwargs["base_url"] = base_url
    if _provider() == "Groq":
        kwargs["max_retries"] = 0
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


_OUTPUT_CONTRACTS = {
    RequirementParseResult: (
        'Return a JSON object with exactly this shape: '
        '{"requirements":[{"id":"REQ-001","text":"...","type":"functional",'
        '"confidence":0.9,"ambiguity_reason":""}]}. '
        'Include every property shown; type must be functional, non_functional, or ambiguous.'
    ),
    ComponentExtractionResult: (
        'Return a JSON object with exactly this shape: '
        '{"components":[{"name":"...","responsibility":"...",'
        '"requirement_ids":["REQ-001"],"technologies":[]}]}. '
        'Include every property shown; use an empty list when there are no technologies or IDs.'
    ),
    ArchitectureSynthesisResult: (
        'Return a JSON object with exactly these properties: '
        '{"style":"...","components":[{"name":"...","responsibility":"...",'
        '"requirement_ids":["REQ-001"],"technologies":[]}],'
        '"relationships":[{"source":"...","target":"...","kind":"...","rationale":"..."}],'
        '"patterns":[],"architectural_summary":"..."}. '
        'Include every property shown and use empty lists when there are no entries.'
    ),
    RationaleResult: (
        'Return a JSON object with exactly this shape: '
        '{"trace_links":[{"requirement_id":"REQ-001","architectural_element":"...",'
        '"decision":"...","rationale":"...","confidence":0.9}],'
        '"warnings":[],"review_notes":[]}. '
        'Include all three top-level properties and every trace-link property. '
        'Return warnings:[] and review_notes:[] when there are none; never omit review_notes.'
    ),
}


def _with_output_contract(prompt: str, text_format: type[BaseModel]) -> str:
    return f"{prompt}\n\nOutput contract: {_OUTPUT_CONTRACTS[text_format]}"


_MAX_GROQ_RATE_LIMIT_RETRIES = 3
_GROQ_BACKOFF_BASE_SECONDS = 1.0
_GROQ_BACKOFF_MAX_SECONDS = 8.0


def _duration_seconds(value: str) -> float | None:
    value = value.strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s|sec|m|min|h)?", value)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2)
    multiplier = {"ms": 0.001, "m": 60, "min": 60, "h": 3600}.get(unit, 1)
    return max(0.0, amount * multiplier)


def _groq_retry_delay(error: Exception, attempt: int) -> float:
    headers = getattr(getattr(error, "response", None), "headers", {}) or {}
    server_delays = []
    for name in ("retry-after-ms", "retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        value = headers.get(name)
        if value is None:
            continue
        value_text = str(value)
        delay = _duration_seconds(value_text)
        if name == "retry-after-ms" and delay is not None and re.fullmatch(r"\s*\d+(?:\.\d+)?\s*", value_text):
            delay *= 0.001
        if delay is None and name == "retry-after":
            try:
                retry_at = parsedate_to_datetime(str(value))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                pass
        if delay is not None:
            server_delays.append(delay)
    backoff = min(_GROQ_BACKOFF_BASE_SECONDS * (2 ** attempt), _GROQ_BACKOFF_MAX_SECONDS)
    return max([backoff, *server_delays])


def _groq_responses_parse(client: OpenAI, **kwargs):
    for attempt in range(_MAX_GROQ_RATE_LIMIT_RETRIES + 1):
        try:
            return client.responses.parse(**kwargs)
        except Exception as exc:
            if (
                _provider() != "Groq"
                or RateLimitError is None
                or not isinstance(exc, RateLimitError)
                or attempt == _MAX_GROQ_RATE_LIMIT_RETRIES
            ):
                raise
            time.sleep(_groq_retry_delay(exc, attempt))


def _is_ollama() -> bool:
    base_url = os.getenv("LLM_BASE_URL", "").lower()
    return "localhost:11434" in base_url or "127.0.0.1:11434" in base_url


def _ollama_text_from_message(message: object) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _ollama_debug_details(response: object) -> str:
    try:
        choice = getattr(response, "choices", [None])[0]
    except (IndexError, TypeError):
        choice = None
    message = getattr(choice, "message", None) if choice is not None else None
    reasoning = getattr(message, "reasoning", None) if message is not None else None
    reasoning_content = getattr(message, "reasoning_content", None) if message is not None else None
    content = _ollama_text_from_message(message)
    return (
        f"model={_model()} base_url={os.getenv('LLM_BASE_URL', '')} "
        f"has_reasoning={bool(reasoning or reasoning_content)} reasoning_preview={str(reasoning or reasoning_content)[:400]!r} "
        f"content_preview={content[:400]!r}"
    )


def _requirement_type_for_text(text: str) -> Literal["functional", "non_functional", "ambiguous"]:
    low = text.lower()
    if any(k in low for k in ["secure", "audit", "privacy", "availability", "performance", "latency", "reliable", "encrypt", "compliance"]):
        return "non_functional"
    if len(text.split()) < 4 or any(k in low for k in ["fast", "easy", "appropriate", "something", "etc"]):
        return "ambiguous"
    return "functional"


def _normalize_ollama_payload(data: dict, expected_type: type[BaseModel]) -> dict:
    if not isinstance(data, dict):
        return data

    if expected_type is RequirementParseResult:
        for key in ["requirements", "atomic_requirements", "items"]:
            if key in data and isinstance(data[key], list):
                data = {**data, "requirements": data[key]}
                break
        if "requirements" not in data:
            if all(isinstance(v, dict) for v in data.values()):
                data = {"requirements": list(data.values())}
            elif all(isinstance(v, str) for v in data.values()):
                items = [{"id": f"REQ-{i:03d}", "text": value, "type": _requirement_type_for_text(value), "confidence": 0.9, "ambiguity_reason": ""} for i, value in enumerate(data.values(), 1)]
                data = {"requirements": items}

        if "requirements" in data and isinstance(data["requirements"], list):
            reqs = []
            for idx, item in enumerate(data["requirements"], 1):
                if isinstance(item, str):
                    reqs.append({
                        "id": f"REQ-{idx:03d}",
                        "text": item,
                        "type": _requirement_type_for_text(item),
                        "confidence": 0.9,
                        "ambiguity_reason": "",
                    })
                elif isinstance(item, dict):
                    req = dict(item)
                    req.setdefault("id", f"REQ-{idx:03d}")
                    req.setdefault("text", req.get("description") or req.get("requirement") or "")
                    req.setdefault("type", _requirement_type_for_text(str(req.get("text", ""))))
                    req.setdefault("confidence", 0.9)
                    req.setdefault("ambiguity_reason", "")
                    reqs.append(req)
            data = {"requirements": reqs}

    elif expected_type is ComponentExtractionResult:
        for key in ["components", "architectural_components", "items"]:
            if key in data and isinstance(data[key], list):
                data = {**data, "components": data[key]}
                break
        if "components" in data and isinstance(data["components"], list):
            component_items = []
            for idx, item in enumerate(data["components"], 1):
                if isinstance(item, str):
                    component_items.append({
                        "name": item,
                        "responsibility": f"Handles {item.lower()}.",
                        "requirement_ids": [],
                        "technologies": [],
                    })
                elif isinstance(item, dict):
                    comp = dict(item)
                    comp.setdefault("name", f"Component-{idx:02d}")
                    comp.setdefault("responsibility", "")
                    comp.setdefault("requirement_ids", [])
                    comp.setdefault("technologies", [])
                    component_items.append(comp)
            data = {"components": component_items}
        elif "components" not in data and isinstance(data, dict):
            values = list(data.values())
            if values and all(isinstance(v, dict) for v in values):
                data = {"components": values}

    elif expected_type is ArchitectureSynthesisResult:
        if "style" not in data:
            data["style"] = "Layered"
        if "components" not in data and "architectural_components" in data:
            data = {**data, "components": data["architectural_components"]}
        if "relationships" not in data and "edges" in data:
            data = {**data, "relationships": data["edges"]}
        if "patterns" not in data and "recommended_patterns" in data:
            data = {**data, "patterns": data["recommended_patterns"]}
        if "architectural_summary" not in data and "summary" in data:
            data = {**data, "architectural_summary": data["summary"]}
        if "architectural_summary" not in data:
            data["architectural_summary"] = "Architecture synthesized from the provided requirements."
        if "components" in data and isinstance(data["components"], list):
            component_items = []
            for idx, item in enumerate(data["components"], 1):
                if isinstance(item, str):
                    component_items.append({
                        "name": item,
                        "responsibility": "",
                        "requirement_ids": [],
                        "technologies": [],
                    })
                elif isinstance(item, dict):
                    comp = dict(item)
                    comp.setdefault("name", f"Component-{idx:02d}")
                    comp.setdefault("responsibility", "")
                    comp.setdefault("requirement_ids", [])
                    comp.setdefault("technologies", [])
                    component_items.append(comp)
            data["components"] = component_items
        if "relationships" in data and isinstance(data["relationships"], dict):
            rels = []
            for source, info in data["relationships"].items():
                if isinstance(info, dict):
                    for target, rationale in info.items():
                        rels.append({"source": source, "target": target, "kind": "depends_on", "rationale": rationale})
                else:
                    rels.append({"source": source, "target": "", "kind": "depends_on", "rationale": str(info)})
            data["relationships"] = rels
        if "patterns" in data and isinstance(data["patterns"], str):
            data["patterns"] = [data["patterns"]]
        if "relationships" not in data:
            data["relationships"] = []
        if "patterns" not in data:
            data["patterns"] = []

    elif expected_type is RationaleResult:
        if "trace_links" not in data and "links" in data:
            data = {**data, "trace_links": data["links"]}
        if "warnings" not in data and "issues" in data:
            data = {**data, "warnings": data["issues"]}
        if "review_notes" not in data and "notes" in data:
            data = {**data, "review_notes": data["notes"]}

        if "trace_links" in data and isinstance(data["trace_links"], list):
            normalized_links = []
            for item in data["trace_links"]:
                if not isinstance(item, dict):
                    continue
                link = dict(item)
                link["architectural_element"] = link.get("architectural_element") or link.get("architect.ural_element") or link.get("element") or ""
                link["requirement_id"] = link.get("requirement_id") or link.get("requirement") or link.get("id") or ""
                link["decision"] = link.get("decision") or link.get("title") or ""
                link["rationale"] = link.get("rationale") or link.get("reason") or ""
                if isinstance(link.get("confidence"), str):
                    conf = link["confidence"].strip().lower()
                    mapping = {"low": 0.3, "medium": 0.6, "high": 0.9}
                    link["confidence"] = mapping.get(conf, 0.9)
                elif link.get("confidence") is None:
                    link["confidence"] = 0.9
                normalized_links.append(link)
            data["trace_links"] = normalized_links

        for key in ["warnings", "review_notes"]:
            if key in data and isinstance(data[key], str):
                data[key] = [data[key]]
            elif key in data and isinstance(data[key], list):
                items = []
                for item in data[key]:
                    if isinstance(item, dict):
                        items.append(item.get("message") or item.get("text") or item.get("note") or str(item))
                    elif item is not None:
                        items.append(str(item))
                data[key] = items

    return data


def _ollama_structured_call(text_format: type[BaseModel], prompt: str, *, max_output_tokens: int) -> BaseModel:
    client = _client()
    schema_hint = {
        RequirementParseResult: 'Return a JSON object with exact top-level key "requirements" and items: {"id":"REQ-001","text":"...","type":"functional","confidence":0.9,"ambiguity_reason":""}.',
        ComponentExtractionResult: 'Return a JSON object with exact top-level key "components" and items: {"name":"Order Service","responsibility":"...","requirement_ids":["REQ-001"],"technologies":["REST"]}.',
        ArchitectureSynthesisResult: 'Return a JSON object with keys: "style", "components", "relationships", "patterns", "architectural_summary".',
        RationaleResult: 'Return a JSON object with keys: "trace_links", "warnings", "review_notes".',
    }.get(text_format, 'Return valid JSON only.')

    for attempt in range(2):
        response = client.chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": SYSTEM_BASE},
                {"role": "user", "content": f"{prompt}\n\n{schema_hint}\nReturn valid JSON only. No markdown fences. No prose outside JSON."},
            ],
            response_format={"type": "json_object"},
            reasoning_effort="none",
            max_tokens=max_output_tokens,
        )

        choice = getattr(response, "choices", [None])[0] if getattr(response, "choices", None) else None
        message = getattr(choice, "message", None) if choice is not None else None
        content = _ollama_text_from_message(message)
        if not content or not content.strip():
            reason_text = getattr(message, "reasoning", None) if message is not None else None
            reason_text = reason_text or getattr(message, "reasoning_content", None) if message is not None else None
            if reason_text:
                if attempt == 0:
                    continue
                raise RuntimeError(
                    "Ollama returned structured-output content only in reasoning/thinking data. "
                    + _ollama_debug_details(response)
                )
            if attempt == 0:
                continue
            raise RuntimeError("Ollama returned empty structured-output content. " + _ollama_debug_details(response))

        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].lstrip()
            cleaned = cleaned.strip()
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3].rstrip()

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            if attempt == 0:
                continue
            raise RuntimeError(f"Ollama returned invalid JSON. {exc.msg} at line {exc.lineno} column {exc.colno}. Raw payload: {cleaned[:500]!r}") from exc

        normalized = _normalize_ollama_payload(payload, text_format)
        if text_format is ArchitectureSynthesisResult and attempt == 0:
            if not normalized.get("style") or not normalized.get("architectural_summary") or not normalized.get("patterns"):
                continue
        try:
            return text_format.model_validate(normalized)
        except Exception:
            if attempt == 0:
                continue
            raise

    raise RuntimeError(f"Qwen/Ollama failed to produce a valid {text_format.__name__} payload after retrying.")


def _parse(text: str) -> RequirementParseResult:
    prompt = f"""Parse the following software requirements into atomic requirements.
Classify each as functional, non_functional, or ambiguous. Mark something ambiguous
when the wording is genuinely underspecified (not merely because it is short).
Assign stable IDs REQ-001, REQ-002, ... in input order.

REQUIREMENTS:\n{text}"""
    if _is_ollama():
        return _ollama_structured_call(RequirementParseResult, prompt, max_output_tokens=2000)

    client = _client()
    response = _groq_responses_parse(client,
        model=_model(),
        instructions=SYSTEM_BASE,
        input=_with_output_contract(prompt, RequirementParseResult),
        **_response_kwargs(text_format=RequirementParseResult, max_output_tokens=2000),
    )
    if not response.output_parsed:
        raise RuntimeError("Model returned no structured requirement output.")
    return response.output_parsed


def _components(reqs: list[Requirement]) -> ComponentExtractionResult:
    payload = "\n".join(f"{r.id} [{r.type}] {r.text}" for r in reqs)
    prompt = f"""Extract the major architectural components needed by these requirements.
Deduplicate overlapping responsibilities. Every functional requirement should map to
one or more components when appropriate; non-functional requirements may be represented
as cross-cutting infrastructure or constraints. Do not create components merely because
a keyword appears. Include likely technologies only when they are justified by the requirements.

REQUIREMENTS:\n{payload}"""
    if _is_ollama():
        return _ollama_structured_call(ComponentExtractionResult, prompt, max_output_tokens=3000)

    client = _client()
    response = _groq_responses_parse(client,
        model=_model(),
        instructions=SYSTEM_BASE,
        input=_with_output_contract(prompt, ComponentExtractionResult),
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
    if _is_ollama():
        result = _ollama_structured_call(ArchitectureSynthesisResult, prompt, max_output_tokens=6000)
    else:
        client = _client()
        response = _groq_responses_parse(client,
            model=_model(),
            instructions=SYSTEM_BASE,
            input=_with_output_contract(prompt, ArchitectureSynthesisResult),
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
    req_text = "\n".join(f"{r.id}: {r.text}" for r in reqs)
    comp_text = "\n".join(f"- {c.name}: {c.responsibility} [{', '.join(c.requirements)}]" for c in arch.components)
    rel_text = "\n".join(f"- {x.source} -> {x.target} ({x.kind}): {x.rationale}" for x in arch.relationships)
    prompt = f"""Act as the reflection/evaluator stage. Review the proposed architecture against the
requirements. Create one or more trace links for every requirement. Each trace link must explain
why the mapped architectural element exists. Identify concrete gaps, contradictions, unsupported
assumptions, or ambiguous requirements in warnings. Review the architecture for consistency and
requirement coverage; do not claim it is correct merely because it is plausible.

REQUIREMENTS:\n{req_text}\n\nARCHITECTURE STYLE: {arch.style}\nCOMPONENTS:\n{comp_text}\n\nRELATIONSHIPS:\n{rel_text}\n\nPATTERNS: {', '.join(arch.patterns)}"""
    if _is_ollama():
        return _ollama_structured_call(RationaleResult, prompt, max_output_tokens=4000)

    client = _client()
    response = _groq_responses_parse(client,
        model=_model(),
        instructions=SYSTEM_BASE,
        input=_with_output_contract(prompt, RationaleResult),
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
