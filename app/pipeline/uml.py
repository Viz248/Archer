import re

from app.models import Architecture, Component, Relationship, Requirement


_EXTERNAL_ENDPOINTS = {"client", "browser", "mobile client"}
_SYSTEM_ACTORS = {"system", "the system", "application", "the application", "platform", "the platform"}
_SEQUENCE_CUE = re.compile(r"\b(when|after|then|before|once|upon|following|subsequently)\b", re.IGNORECASE)
_AS_A_ACTOR = re.compile(r"^as\s+(?:an?\s+)?([^,]+),", re.IGNORECASE)
_SUBJECT_ACTOR = re.compile(
    r"^(?:the\s+|a\s+|an\s+)?([a-z][a-z0-9 _-]*?)\s+"
    r"(?:shall|can|must|should|will|may)\b",
    re.IGNORECASE,
)


def generate_diagrams(
    requirements: list[Requirement],
    architecture: Architecture,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return target-system Mermaid sources and per-diagram availability notes."""
    architecture_source, architecture_status = architecture_diagram(architecture)
    use_case_source, use_case_status = use_case_diagram(requirements)
    flow = _sequence_path(requirements, architecture)
    sequence_source, sequence_status = sequence_diagram(flow)
    activity_source, activity_status = activity_diagram(flow)

    return (
        {
            "architecture": architecture_source,
            "use_case": use_case_source,
            "sequence": sequence_source,
            "activity": activity_source,
            "class": "",
        },
        {
            "architecture": architecture_status,
            "use_case": use_case_status,
            "sequence": sequence_status,
            "activity": activity_status,
            "class": (
                "unavailable: Structured input contains services/components, not domain entities "
                "and entity relationships suitable for a class diagram."
            ),
        },
    )


def architecture_diagram(architecture: Architecture) -> tuple[str, str]:
    if not architecture.components:
        return "", "unavailable: No synthesized target-system components are available."

    component_ids = {component.name.casefold(): f"C{index}" for index, component in enumerate(architecture.components)}
    endpoint_ids = dict(component_ids)
    external_names: list[str] = []
    for relationship in architecture.relationships:
        for endpoint in (relationship.source, relationship.target):
            if not isinstance(endpoint, str):
                continue
            normalized = endpoint.strip().casefold()
            if normalized not in endpoint_ids and _is_external_endpoint(endpoint) and normalized not in {
                name.casefold() for name in external_names
            }:
                external_names.append(endpoint.strip())
    for index, name in enumerate(external_names):
        endpoint_ids[name.casefold()] = f"X{index}"

    lines = ["flowchart TD"]
    lines.extend(
        f'    C{index}["{_mermaid_label(component.name)}: {_mermaid_label(component.responsibility)}"]'
        for index, component in enumerate(architecture.components)
    )
    lines.extend(
        f'    X{index}(["External: {_mermaid_label(name)}"])'
        for index, name in enumerate(external_names)
    )

    valid_relationships = []
    for relationship in architecture.relationships:
        source = endpoint_ids.get(str(relationship.source).strip().casefold())
        target = endpoint_ids.get(str(relationship.target).strip().casefold())
        if source and target and isinstance(relationship.kind, str) and relationship.kind.strip():
            valid_relationships.append((source, target, relationship))
    lines.extend(
        f"    {source} -->|{_mermaid_label(relationship.kind)}| {target}"
        for source, target, relationship in valid_relationships
    )
    lines.append("    classDef component fill:#e8f1fb,stroke:#315f8c,color:#14283d,stroke-width:1.5px")
    lines.append("    classDef external fill:#f3f4f6,stroke:#6b7280,color:#303846")
    if architecture.components:
        lines.append("    class " + ",".join(f"C{index}" for index in range(len(architecture.components))) + " component")
    if external_names:
        lines.append("    class " + ",".join(f"X{index}" for index in range(len(external_names))) + " external")

    invalid_count = len(architecture.relationships) - len(valid_relationships)
    status = "available"
    if invalid_count:
        status += f"; omitted {invalid_count} relationship(s) with missing/invalid component endpoints or type"
    return "\n".join(lines), status


def use_case_diagram(requirements: list[Requirement]) -> tuple[str, str]:
    functional_requirements = [requirement for requirement in requirements if requirement.type == "functional"]
    if not functional_requirements:
        return "", "unavailable: No functional requirements were parsed."

    actors: dict[str, tuple[str, int]] = {}
    requirement_actors: dict[str, str] = {}
    for requirement in functional_requirements:
        actor = _explicit_actor(requirement.text)
        if actor:
            normalized = actor.casefold()
            if normalized not in actors:
                actors[normalized] = (actor, len(actors))
            requirement_actors[requirement.id] = f"A{actors[normalized][1]}"

    lines = ["flowchart LR"]
    if actors:
        lines.extend(
            f'    A{index}(["{_mermaid_label(actor)}"])'
            for actor, index in actors.values()
        )
    lines.append('    subgraph TARGET["Target system use-case representation"]')
    for index, requirement in enumerate(functional_requirements):
        label = f"{requirement.id}: {requirement.text}"
        lines.append(f'        U{index}(["{_mermaid_label(label)}"])')
    lines.append("    end")
    for index, requirement in enumerate(functional_requirements):
        actor_id = requirement_actors.get(requirement.id)
        if actor_id:
            lines.append(f"    {actor_id} --> U{index}")
    return "\n".join(lines), "available"


def sequence_diagram(path: list[Relationship]) -> tuple[str, str]:
    if not path:
        return "", (
            "unavailable: Requirements and architecture relationships do not establish an ordered "
            "multi-component scenario."
        )

    participants = []
    for relationship in path:
        for name in (relationship.source, relationship.target):
            if name not in participants:
                participants.append(name)
    ids = {name: f"P{index}" for index, name in enumerate(participants)}
    lines = ["sequenceDiagram"]
    lines.extend(f'    participant {ids[name]} as "{_mermaid_label(name)}"' for name in participants)
    for relationship in path:
        arrow = "-)" if _is_async_relationship(relationship.kind) else "->"
        lines.append(
            f'    {ids[relationship.source]}{arrow}{ids[relationship.target]}: '
            f'{_mermaid_label(relationship.kind)}'
        )
    return "\n".join(lines), "available"


def activity_diagram(path: list[Relationship]) -> tuple[str, str]:
    if not path:
        return "", (
            "unavailable: Requirements and directed architecture relationships do not establish "
            "a target-system workflow."
        )

    nodes = [path[0].source] + [relationship.target for relationship in path]
    ids = {name: f"S{index}" for index, name in enumerate(nodes)}
    lines = ["flowchart TD", '    START(["Start"])']
    lines.extend(f'    {ids[name]}["{_mermaid_label(name)}"]' for name in nodes)
    lines.append('    FINISH(["End"])')
    lines.append(f"    START --> {ids[nodes[0]]}")
    for relationship in path:
        lines.append(
            f"    {ids[relationship.source]} -->|{_mermaid_label(relationship.kind)}| "
            f'{ids[relationship.target]}'
        )
    lines.append(f"    {ids[nodes[-1]]} --> FINISH")
    return "\n".join(lines), "available"


def use_case(requirements: list[Requirement]) -> str:
    return use_case_diagram(requirements)[0]


def class_diagram(architecture: Architecture) -> str:
    return ""


def sequence(architecture: Architecture, requirements: list[Requirement] | None = None) -> str:
    if requirements is None:
        return ""
    return sequence_diagram(_sequence_path(requirements, architecture))[0]


def activity(
    architecture: Architecture | None = None,
    requirements: list[Requirement] | None = None,
) -> str:
    if architecture is None or requirements is None:
        return ""
    return activity_diagram(_sequence_path(requirements, architecture))[0]


def internal_workflow_diagrams() -> dict[str, str]:
    return {
        "workflow": """flowchart LR
    R[Requirements input] --> P[Requirement parsing]
    P --> C[Component extraction]
    C --> S[Architecture synthesis]
    S --> E[Evaluation]
    E --> D[Diagram generation]
    D --> X[Report generation]""",
    }


def _sequence_path(requirements: list[Requirement], architecture: Architecture) -> list[Relationship]:
    components = {component.name.casefold(): component for component in architecture.components}
    for requirement in requirements:
        if requirement.type != "functional" or not _SEQUENCE_CUE.search(requirement.text):
            continue
        mapped = {
            component.name.casefold()
            for component in architecture.components
            if requirement.id in component.requirements
        }
        if not mapped:
            continue
        requirement_terms = _content_terms(requirement.text)
        relevance = {
            component.name.casefold(): _component_relevance(component, requirement_terms)
            for component in architecture.components
        }
        relevant_nodes = {name for name, score in relevance.items() if score > 0} or mapped
        eligible = []
        for relationship in architecture.relationships:
            source = relationship.source.strip().casefold() if isinstance(relationship.source, str) else ""
            target = relationship.target.strip().casefold() if isinstance(relationship.target, str) else ""
            if source not in components or target not in components:
                continue
            if source in relevant_nodes and target in relevant_nodes and (source in mapped or target in mapped):
                eligible.append(relationship)
        scenario_mapped = mapped & relevant_nodes
        path = _shortest_mapped_path(eligible, scenario_mapped, requirement_terms, components)
        if path:
            return path
        if eligible:
            eligible.sort(
                key=lambda relationship: (
                    -_relationship_relevance(relationship, requirement_terms, components),
                    architecture.relationships.index(relationship),
                )
            )
            return [eligible[0]]
    return []


def _shortest_mapped_path(
    relationships: list[Relationship],
    mapped_nodes: set[str],
    requirement_terms: set[str],
    components: dict[str, Component],
) -> list[Relationship]:
    adjacency: dict[str, list[Relationship]] = {}
    for relationship in relationships:
        adjacency.setdefault(relationship.source.casefold(), []).append(relationship)
    candidates: list[list[Relationship]] = []
    shortest_length: int | None = None
    for start in mapped_nodes:
        queue = [(start, [], {start})]
        while queue:
            node, path, visited = queue.pop(0)
            if path and node in mapped_nodes and node != start:
                if shortest_length is None or len(path) < shortest_length:
                    shortest_length = len(path)
                    candidates = [path]
                elif len(path) == shortest_length:
                    candidates.append(path)
                continue
            if shortest_length is not None and len(path) >= shortest_length:
                continue
            for relationship in adjacency.get(node, []):
                target = relationship.target.casefold()
                if target not in visited:
                    queue.append((target, path + [relationship], visited | {target}))
    if not candidates:
        return []
    return max(
        candidates,
        key=lambda path: sum(
            _relationship_relevance(relationship, requirement_terms, components)
            for relationship in path
        ),
    )


def _relationship_relevance(
    relationship: Relationship,
    requirement_terms: set[str],
    components: dict[str, Component],
) -> int:
    score = 0
    for endpoint in (relationship.source, relationship.target):
        component = components.get(endpoint.casefold())
        if component:
            name_terms = set(re.findall(r"[a-z0-9]+", component.name.casefold()))
            name_terms -= {"service", "system", "infrastructure", "management"}
            score += len(name_terms & requirement_terms)
    rationale_terms = set(re.findall(r"[a-z0-9]+", relationship.rationale.casefold()))
    score += len(rationale_terms & requirement_terms)
    if _is_async_relationship(relationship.kind) and any(term in requirement_terms for term in ("event", "notify", "notification")):
        score += 1
    return score


def _content_terms(text: str) -> set[str]:
    stop_words = {
        "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with",
        "system", "shall", "should", "must", "can", "will", "may", "when", "then", "after", "before", "upon",
        "sends", "send", "sent", "provides", "provide", "provided", "supports", "support", "supported",
    }
    return set(re.findall(r"[a-z0-9]+", text.casefold())) - stop_words


def _component_relevance(component: Component, requirement_terms: set[str]) -> int:
    component_terms = _content_terms(f"{component.name} {component.responsibility}")
    component_terms -= {"service", "system", "infrastructure", "management", "handles", "capability"}
    return len(component_terms & requirement_terms)


def _explicit_actor(text: str) -> str:
    match = _AS_A_ACTOR.match(text.strip())
    if not match:
        match = _SUBJECT_ACTOR.match(text.strip())
    if not match:
        return ""
    actor = " ".join(match.group(1).strip().split())
    if actor.casefold() in _SYSTEM_ACTORS:
        return ""
    return actor


def _is_external_endpoint(name: str) -> bool:
    normalized = name.strip().casefold()
    return normalized in _EXTERNAL_ENDPOINTS or normalized.startswith("external ")


def _is_async_relationship(kind: str) -> bool:
    return bool(re.search(r"\b(event|publish|subscribe|notification|async|message)\b", kind, re.IGNORECASE))


def _mermaid_label(value: str) -> str:
    replacements = {
        "&": "#amp;", '"': "#quot;", "'": "#39;", "<": "#lt;", ">": "#gt;",
        "#": "#35;", "|": "#124;", "[": "#91;", "]": "#93;", "{": "#123;",
        "}": "#125;", "`": "#96;", "\\": "#92;", "\n": " ", "\r": " ",
    }
    return "".join(replacements.get(character, character) for character in str(value))
