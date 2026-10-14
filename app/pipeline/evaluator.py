"""Deterministic architecture checks that complement semantic reflection."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from app.models import (
    Architecture,
    EvaluationFinding,
    Requirement,
    RequirementAssessment,
    TraceLink,
)


_EXTERNAL_ENDPOINTS = {"client", "browser", "mobile client"}
_AVAILABILITY_REQUIREMENT = re.compile(
    r"\b(high[- ]availability|availability|uptime|fault[- ]toleran\w*|disaster recovery)\b",
    re.IGNORECASE,
)
_AVAILABILITY_MECHANISM = re.compile(
    r"\b(redundan\w*|replic\w*|failover|health checks?|heartbeats?|"
    r"load balanc\w*|active[- ]active|active[- ]passive|multi[- ]region|"
    r"cluster(?:ing)?|automatic recovery|self[- ]healing|zone[- ]redundan\w*|hot standby)\b",
    re.IGNORECASE,
)
_AVAILABILITY_CONCRETE_DETAIL = re.compile(
    r"\b(?:two|three|multiple|several|at least\s+\d+|\d+)\s+"
    r"(?:(?:active|standby|hot|warm|cold)\s+)?(?:replicas?|instances?|nodes?|zones?|regions?)\b"
    r"|\bactive[- ](?:active|passive)\b|\b(?:multi[- ]region|zone[- ]redundan\w*)\b"
    r"|\b(?:automatic|automated|manual)\s+failover\b|\bfailover\s+to\b"
    r"|\bhealth checks?.{0,50}\b(?:trigger|detect|cause|initiate|start|route|switch|remove|restart)\w*\b"
    r"|\b(?:trigger|detect|cause|initiate|start|route|switch|remove|restart)\w*.{0,50}\bhealth checks?\b"
    r"|\bload balanc\w*.{0,50}\b(?:across|between|multiple|replicas?|instances?|nodes?|distribut\w*|routes? traffic)\b"
    r"|\b(?:replic\w*|distribut\w*).{0,50}\b(?:across|between)\s+(?:availability )?(?:zones?|regions?|nodes?)\b"
    r"|\bautomatic recovery\b",
    re.IGNORECASE,
)
_AVAILABILITY_TARGET = re.compile(
    r"\b\d{2,3}(?:\.\d+)?\s*%(?!\w)|\b(?:three|four|five)\s+nines\b"
    r"|\b(?:rto|rpo)\s*(?:(?:<=|>=|[<>=])\s*|(?:of|is|:)\s*)?\d+\b"
    r"|\b(?:within|under|less than|no more than)\s+\d+\s*(?:seconds?|minutes?|hours?|days?)\b",
    re.IGNORECASE,
)
_PATTERN_COMPONENTS = {
    "api gateway": "API Gateway",
    "circuit breaker": "Circuit Breaker",
    "load balancer": "Load Balancer",
}
_NON_DEPENDENCY_KINDS = {
    "event", "publishes", "subscribes", "callback", "response", "reply",
    "notification", "bidirectional", "async-event", "async_event",
}
_NON_DEPENDENCY_KIND_TOKENS = {
    "async", "asynchronous", "event", "events", "publish", "publishes", "published",
    "publishing", "subscribe", "subscribes", "subscription", "consume", "consumes",
    "consumer", "dispatch", "dispatched", "delivery", "deliver", "delivers",
    "topic", "message", "messages", "broker", "response", "reply", "callback",
    "notification", "bidirectional",
}
_EXPLICIT_BIDIRECTIONAL = re.compile(
    r"\b(bidirectional|request[- /]response|callback|reply channel|"
    r"asynchronous event|event-driven communication)\b",
    re.IGNORECASE,
)
_AVAILABILITY_NONASSERTION_BEFORE = re.compile(
    r"\b(no|not|without|lack\w*|never|doesn't|does not|isn't|is not|aren't|are not|"
    r"hasn't|has not|haven't|have not|could|may|might|should|must|need|needs|require|"
    r"requires|required|consider|proposed|planned|will)\b",
    re.IGNORECASE,
)
_AVAILABILITY_NONASSERTION_AFTER = re.compile(
    r"^(?:\W*(?:isn't|aren't|wasn't|weren't|hasn't|haven't|doesn't|don't|didn't)\W+"
    r"(?:configured|implemented|deployed|enabled|established|supported|available|in place|present)\b|"
    r"\W*(?:(?:is|are|was|were|has been|have been|will be|could be|may be|might be|should be|"
    r"does|do|did)\W+)?(?:(?:only|just|merely)\W+)?"
    r"(?:not|never|absent|unavailable|disabled|unconfigured|unimplemented|planned|proposed|"
    r"considered|pending|could|may|might|should)\b)",
    re.IGNORECASE,
)


def evaluate_architecture(
    requirements: list[Requirement],
    architecture: Architecture,
    trace_links: list[TraceLink],
    llm_assessments: Iterable[object] | None = None,
) -> tuple[list[RequirementAssessment], list[EvaluationFinding]]:
    """Return requirement statuses and objective findings for an architecture."""
    findings: list[EvaluationFinding] = []
    component_names = {component.name.casefold(): component.name for component in architecture.components}
    requirement_by_id = {requirement.id: requirement for requirement in requirements}
    valid_trace_links: dict[str, list[TraceLink]] = defaultdict(list)

    for link in trace_links:
        requirement = requirement_by_id.get(link.requirement_id)
        if requirement is None:
            findings.append(_finding(
                "unknown_trace_requirement", "Trace link", [],
                f"Trace link references unknown requirement {link.requirement_id}.",
                "The link cannot establish coverage for a supplied requirement.",
                "Correct or remove the trace link while preserving the source requirement IDs.",
            ))
            continue
        if not _is_architecture_element(link.architectural_element, component_names):
            findings.append(_finding(
                "invalid_trace_target", f"{link.requirement_id} trace link", [link.requirement_id],
                f"Trace link targets nonexistent architecture element '{link.architectural_element}'.",
                "A dangling mapping gives the appearance of coverage without pointing to an architectural decision.",
                "Map the requirement to an existing component or explicitly describe its cross-cutting architectural decision.",
            ))
            continue
        valid_trace_links[link.requirement_id].append(link)

    assessment_by_id: dict[str, object] = {}
    duplicate_assessment_ids: set[str] = set()
    llm_was_run = llm_assessments is not None
    if llm_assessments is not None:
        for assessment in llm_assessments:
            requirement_id = getattr(assessment, "requirement_id", None)
            if requirement_id not in requirement_by_id:
                findings.append(_finding(
                    "unknown_assessment_requirement", "Requirement assessment", [],
                    f"Evaluator returned an assessment for unknown requirement {requirement_id!r}.",
                    "Assessment output cannot be tied back to the supplied requirements.",
                    "Return exactly one assessment for each original requirement ID.",
                ))
                continue
            if requirement_id in assessment_by_id:
                duplicate_assessment_ids.add(requirement_id)
                findings.append(_finding(
                    "duplicate_requirement_assessment", requirement_id, [requirement_id],
                    f"The reflection stage returned more than one satisfaction assessment for {requirement_id}.",
                    "Conflicting statuses or gaps make requirement coverage ambiguous.",
                    "Return exactly one assessment for the original requirement ID.",
                ))
                continue
            assessment_by_id[requirement_id] = assessment

    assessments: list[RequirementAssessment] = []
    for requirement in requirements:
        links = valid_trace_links.get(requirement.id, [])
        llm_assessment = assessment_by_id.get(requirement.id)
        evidence: list[str] = []
        gaps: list[str] = []

        if not links:
            status = "unresolved"
            if llm_assessment is not None:
                evidence_text = getattr(llm_assessment, "evidence", "")
                if evidence_text:
                    evidence.append(str(evidence_text))
                gaps.extend(str(gap) for gap in getattr(llm_assessment, "gaps", []) if gap)
            if "No valid trace link maps this requirement to an existing architecture element." not in gaps:
                gaps.append("No valid trace link maps this requirement to an existing architecture element.")
            findings.append(_finding(
                "requirement_unmapped", requirement.id, [requirement.id],
                f"{requirement.id} has no valid architecture mapping. Reflection detail: {_gap_summary(gaps)}",
                "A requirement without a valid mapping cannot be reviewed for implementation coverage.",
                "Map it to an existing component or record the explicit cross-cutting decision that addresses it.",
            ))
        elif requirement.id in duplicate_assessment_ids:
            status = "unresolved"
            evidence.extend(_link_evidence(links))
            gaps.append("The reflection stage returned conflicting duplicate assessments for this requirement.")
        elif llm_was_run and llm_assessment is None:
            status = "unresolved"
            evidence.extend(_link_evidence(links))
            gaps.append("The reflection stage returned no satisfaction assessment for this requirement.")
            findings.append(_finding(
                "assessment_missing", requirement.id, [requirement.id],
                f"{requirement.id} is mapped but was not evaluated for satisfaction.",
                "Traceability alone does not demonstrate that the requirement is fully addressed.",
                "Assess the architectural evidence and state any remaining gap for this requirement.",
            ))
        elif llm_assessment is None:
            status = "mapped"
            evidence.extend(_link_evidence(links))
        else:
            model_status = getattr(llm_assessment, "status", "unresolved")
            evidence_text = getattr(llm_assessment, "evidence", "")
            evidence.extend(_link_evidence(links))
            if evidence_text:
                evidence.append(str(evidence_text))
            gaps.extend(str(gap) for gap in getattr(llm_assessment, "gaps", []) if gap)
            status = {
                "satisfied": "satisfied",
                "mapped": "mapped",
                "partially_satisfied": "partially_satisfied",
                "unresolved": "unresolved",
            }.get(model_status, "unresolved")
            if status == "satisfied" and gaps:
                status = "partially_satisfied"
            elif status == "satisfied" and not str(evidence_text).strip():
                status = "unresolved"
                gaps.append("The reflection stage marked the requirement satisfied without citing supporting evidence.")
            if status == "partially_satisfied":
                if not gaps:
                    gaps.append("The reflection stage marked the requirement partially satisfied without specifying the remaining gap.")
                findings.append(_finding(
                    "requirement_partial", requirement.id, [requirement.id],
                    f"{requirement.id} is mapped but only partially satisfied: {_gap_summary(gaps)}",
                    "The trace link identifies relevant architecture, but the stated gap means the requirement is not fully addressed.",
                    "Resolve the listed gap or clarify the requirement and the evidence needed to accept it.",
                ))
            elif status == "unresolved":
                if not gaps:
                    gaps.append("The reflection stage could not establish that the architecture satisfies this requirement.")
                findings.append(_finding(
                    "requirement_unresolved", requirement.id, [requirement.id],
                    f"{requirement.id} has unresolved satisfaction: {_gap_summary(gaps)}",
                    "A mapping exists, but there is insufficient evidence to treat the requirement as addressed.",
                    "Clarify the missing evidence or revise the architecture before claiming coverage.",
                ))

        assessments.append(RequirementAssessment(
            requirement_id=requirement.id,
            status=status,
            evidence=_unique_evidence(evidence),
            gaps=_unique(gaps),
        ))

    findings.extend(_check_relationships(architecture, component_names))
    findings.extend(_check_patterns(architecture, component_names))
    findings.extend(_check_availability(requirements, architecture, assessments, valid_trace_links))
    findings = _dedupe_findings(findings)
    for assessment in assessments:
        assessment.finding_ids = [
            finding.finding_id
            for finding in findings
            if assessment.requirement_id in finding.requirement_ids
        ]
    return assessments, findings


def finding_warning(finding: EvaluationFinding) -> str:
    anchors = ", ".join(finding.requirement_ids) if finding.requirement_ids else finding.subject
    return f"[{finding.finding_id}] {anchors}: {finding.message} Why it matters: {finding.impact} Action: {finding.action}"


def _is_architecture_element(value: str, components: dict[str, str]) -> bool:
    normalized = value.strip().casefold()
    return (
        normalized in components
        or normalized in {"architecture", "cross-cutting", "cross-cutting concern"}
    )


def _link_evidence(links: list[TraceLink]) -> list[str]:
    return [f"Mapped to {link.architectural_element}: {link.rationale}" for link in links]


def _check_relationships(
    architecture: Architecture,
    component_names: dict[str, str],
) -> list[EvaluationFinding]:
    findings: list[EvaluationFinding] = []
    graph: dict[str, set[str]] = {name: set() for name in component_names.values()}

    for relationship in architecture.relationships:
        source = relationship.source
        target = relationship.target
        kind = relationship.kind
        if not isinstance(source, str) or not source.strip() or not isinstance(target, str) or not target.strip():
            findings.append(_finding(
                "invalid_relationship_endpoint", "Relationship", [],
                "Relationship endpoints must be non-empty component or external-boundary names.",
                "An endpoint that is missing or has the wrong type makes the relationship uninterpretable.",
                "Provide valid source and target names matching the architecture schema.",
            ))
            continue
        if not isinstance(kind, str) or not kind.strip():
            findings.append(_finding(
                "invalid_relationship_kind", f"{source} -> {target}", [],
                "Relationship kind is missing or is not a string.",
                "Without a valid kind, dependency and communication semantics cannot be evaluated.",
                "Set a concise relationship kind such as service-call, event, or request.",
            ))
            continue
        if not isinstance(relationship.rationale, str):
            findings.append(_finding(
                "invalid_relationship_rationale", f"{source} -> {target}", [],
                "Relationship rationale must be a string according to the architecture schema.",
                "Non-text rationale cannot explain or support the claimed dependency.",
                "Replace it with a concise text explanation grounded in a requirement or necessary architecture behavior.",
            ))
            continue

        unknown = [name for name in (source, target) if not _known_endpoint(name, component_names)]
        if unknown:
            findings.append(_finding(
                "relationship_unknown_component", f"{source} -> {target}", [],
                f"Relationship references nonexistent component endpoint(s): {', '.join(unknown)}.",
                "Dangling relationships can hide missing components or incorrect architecture connections.",
                "Add the intended component or correct the endpoint; use an explicit external-boundary name only for real actors outside the system.",
            ))
            continue
        if _is_dependency(relationship):
            source_name = component_names.get(source.casefold())
            target_name = component_names.get(target.casefold())
            if source_name and target_name:
                graph[source_name].add(target_name)

    for group in _strongly_connected_groups(graph):
        if len(group) == 2:
            subject = " and ".join(group)
            message = f"Suspicious reciprocal service dependencies connect {group[0]} and {group[1]}."
        else:
            subject = ", ".join(group)
            message = f"A possible dependency cycle involves these mutually reachable components: {', '.join(group)}."
        findings.append(_finding(
            "suspicious_dependency_cycle", subject, [], message,
            "Cycles can create tight coupling, deployment ordering constraints, and failure propagation.",
            "Confirm the cycle is intentional; otherwise invert one dependency or use an explicit event/callback contract.",
        ))
    return findings


def _known_endpoint(value: str, component_names: dict[str, str]) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().casefold()
    return (
        normalized in component_names
        or normalized in _EXTERNAL_ENDPOINTS
        or normalized.startswith(("external ", "external:"))
    )


def _is_dependency(relationship: object) -> bool:
    kind = str(getattr(relationship, "kind", "")).strip().casefold().replace(" ", "-")
    rationale = str(getattr(relationship, "rationale", ""))
    normalized_kind = kind.replace("-", "_")
    kind_tokens = set(re.split(r"[^a-z0-9]+", kind))
    if (
        kind in _NON_DEPENDENCY_KINDS
        or normalized_kind in _NON_DEPENDENCY_KINDS
        or kind_tokens.intersection(_NON_DEPENDENCY_KIND_TOKENS)
    ):
        return False
    if _EXPLICIT_BIDIRECTIONAL.search(f"{kind} {rationale}"):
        return False
    return True


def _strongly_connected_groups(graph: dict[str, set[str]]) -> list[list[str]]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    groups: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] == indices[node]:
            group = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                group.append(member)
                if member == node:
                    break
            if len(group) > 1 or node in graph[node]:
                groups.append(sorted(group, key=str.casefold))

    for node in graph:
        if node not in indices:
            visit(node)
    return groups


def _check_patterns(
    architecture: Architecture,
    component_names: dict[str, str],
) -> list[EvaluationFinding]:
    findings = []
    applied_patterns = [pattern for pattern in architecture.patterns if not _is_recommended(pattern)]
    for pattern in applied_patterns:
        normalized = _normalize_pattern(pattern)
        required_component = next((name for key, name in _PATTERN_COMPONENTS.items() if key in normalized), None)
        if required_component is None:
            continue
        represented_component = next(
            (name for name in component_names.values() if required_component.casefold() in name.casefold()),
            None,
        )
        relationship_represents_pattern = any(
            required_component.casefold() in f"{rel.kind} {rel.rationale}".casefold()
            and _known_endpoint(rel.source, component_names)
            and _known_endpoint(rel.target, component_names)
            for rel in architecture.relationships
        )
        if represented_component is None and not relationship_represents_pattern:
            findings.append(_finding(
                "applied_pattern_unrepresented", pattern, [],
                f"Applied {pattern} is not represented by a component or a corresponding relationship.",
                "The pattern claim cannot be verified from the architecture and may mislead reviewers about implemented structure.",
                f"Add the {required_component} structure and its connections, or move the pattern to recommended patterns.",
            ))
        elif represented_component and not relationship_represents_pattern:
            connected = any(
                rel.source.casefold() == represented_component.casefold()
                or rel.target.casefold() == represented_component.casefold()
                for rel in architecture.relationships
                if isinstance(rel.source, str) and isinstance(rel.target, str)
            )
            if not connected:
                findings.append(_finding(
                    "applied_pattern_unconnected", pattern, [],
                    f"{required_component} is present but has no relationship to the architecture.",
                    "A disconnected pattern component does not demonstrate that the pattern participates in system behavior.",
                    f"Connect {required_component} to the components it mediates, or mark the pattern as recommended.",
                ))
    return findings


def _is_recommended(pattern: str) -> bool:
    return bool(re.search(
        r"(?:\brecommended\b|\bnot yet applied\s*$)",
        pattern.strip(),
        re.IGNORECASE,
    ))


def _normalize_pattern(pattern: str) -> str:
    value = re.sub(r"^(applied|recommended)\s*:\s*", "", pattern.strip(), flags=re.IGNORECASE)
    value = re.sub(r"\s*(?:[-:(]\s*|is\s+)?recommended\s*[)\]]?\s*$", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*[-:]?\s*not yet applied\s*$", "", value, flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _check_availability(
    requirements: list[Requirement],
    architecture: Architecture,
    assessments: list[RequirementAssessment],
    trace_links: dict[str, list[TraceLink]],
) -> list[EvaluationFinding]:
    findings = []
    assessment_by_id = {item.requirement_id: item for item in assessments}
    for requirement in requirements:
        if not _AVAILABILITY_REQUIREMENT.search(requirement.text):
            continue
        assessment = assessment_by_id[requirement.id]
        if not _AVAILABILITY_TARGET.search(requirement.text):
            if assessment.status in {"mapped", "satisfied"}:
                assessment.status = "partially_satisfied"
            gap = "The requirement has no measurable uptime/availability target, RTO, or RPO for acceptance."
            if gap not in assessment.gaps:
                assessment.gaps.append(gap)
            findings.append(_finding(
                "availability_target_unspecified", requirement.id, [requirement.id],
                f"{requirement.id} requests availability without a measurable acceptance target.",
                "Without an uptime target or recovery objective, reviewers cannot determine whether the architecture is sufficient.",
                "Specify an uptime percentage or an RTO/RPO target appropriate to the system.",
            ))
        linked_components = {
            component.name.casefold()
            for component in architecture.components
            if requirement.id in component.requirements
            or any(
                link.architectural_element.casefold() == component.name.casefold()
                for link in trace_links.get(requirement.id, [])
            )
        }
        relevant_details = [
            component.responsibility
            for component in architecture.components
            if component.name.casefold() in linked_components
        ]
        relevant_details.extend(
            f"{relationship.kind} {relationship.rationale}"
            for relationship in architecture.relationships
            if (
                (isinstance(relationship.source, str) and relationship.source.casefold() in linked_components)
                or (isinstance(relationship.target, str) and relationship.target.casefold() in linked_components)
                or requirement.id.casefold() in f"{relationship.kind} {relationship.rationale}".casefold()
            )
        )
        if _has_asserted_availability_mechanism("\n".join(relevant_details)):
            continue
        if assessment.status in {"mapped", "satisfied"}:
            assessment.status = "partially_satisfied"
        gap = (
            "No concrete availability mechanism is described in component responsibilities or relationships; "
            "a component name alone is not evidence of redundancy, health checks, failover, or load balancing."
        )
        if gap not in assessment.gaps:
            assessment.gaps.append(gap)
        findings.append(_finding(
            "availability_mechanism_unspecified", requirement.id, [requirement.id],
            f"{requirement.id} claims availability support without a concrete mechanism in the architecture.",
            "A named high-availability component does not establish how failures are detected or service is maintained.",
            "Specify the intended redundancy, health-check, failover, load-balancing, or equivalent mechanism and clarify recovery expectations.",
        ))
    return findings


def _has_asserted_availability_mechanism(details: str) -> bool:
    for match in _AVAILABILITY_MECHANISM.finditer(details):
        preceding_clause = re.split(r"[.;\n]", details[:match.start()])[-1]
        preceding_words = re.findall(r"[a-z]+", preceding_clause.casefold())[-6:]
        if _AVAILABILITY_NONASSERTION_BEFORE.search(" ".join(preceding_words)):
            continue
        following = details[match.end():match.end() + 60]
        if _AVAILABILITY_NONASSERTION_AFTER.search(following):
            continue
        nearby_detail = details[max(0, match.start() - 70):match.end() + 70]
        if _AVAILABILITY_CONCRETE_DETAIL.search(nearby_detail):
            return True
    return False


def _finding(
    code: str,
    subject: str,
    requirement_ids: list[str],
    message: str,
    impact: str,
    action: str,
) -> EvaluationFinding:
    return EvaluationFinding(
        code=code,
        severity="warning",
        subject=subject,
        requirement_ids=requirement_ids,
        message=message,
        impact=impact,
        action=action,
    )


def _gap_summary(gaps: list[str]) -> str:
    return "; ".join(gaps) if gaps else "no specific evidence or gap was returned"


def _unique(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        normalized = value.strip().casefold()
        if normalized and normalized not in seen:
            result.append(value)
            seen.add(normalized)
    return result


def _unique_evidence(values: list[str]) -> list[str]:
    result = []
    seen_claims: set[str] = set()
    seen_mappings: set[tuple[str, str]] = set()
    for value in values:
        mapping = re.match(r"^Mapped to (.+?):\s*(.*)$", value.strip(), re.IGNORECASE)
        component = mapping.group(1).strip().casefold() if mapping else ""
        text = mapping.group(2) if mapping else value
        kept_sentences = []
        for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
            normalized = re.sub(r"\s+", " ", sentence).strip(" \t.!?").casefold()
            if not normalized:
                continue
            if mapping:
                mapping_key = (component, normalized)
                if mapping_key in seen_mappings:
                    continue
                seen_mappings.add(mapping_key)
                kept_sentences.append(
                    f"Mapped to {mapping.group(1).strip()}: {sentence.strip()}"
                    if not kept_sentences else sentence.strip()
                )
            elif normalized not in seen_claims:
                kept_sentences.append(sentence.strip())
            seen_claims.add(normalized)
        if kept_sentences:
            result.append(" ".join(kept_sentences))
    return result


def _dedupe_findings(findings: list[EvaluationFinding]) -> list[EvaluationFinding]:
    result = []
    seen = set()
    for finding in findings:
        key = finding.finding_id
        if key not in seen:
            seen.add(key)
            result.append(finding)
    return result