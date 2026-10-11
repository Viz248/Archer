import re

from app.models import Architecture, Component, Relationship, Requirement


_MODAL_SUBJECT = re.compile(
    r"^(?:the\s+|a\s+|an\s+)?([a-z][a-z0-9 _-]*?)\s+"
    r"(?:shall|can|must|should|will|may)\b",
    re.IGNORECASE,
)
_AS_ACTOR = re.compile(r"^as\s+(?:an?\s+)?([^,]+),", re.IGNORECASE)
_SYSTEM_ACTORS = {"system", "the system", "application", "the application", "platform", "the platform"}
_TRIGGER_CLAUSE = re.compile(r"\b(?:when|after|once|upon)\b", re.IGNORECASE)
_AUTH_REQUIREMENT = re.compile(r"\b(authenticat\w*|login|log in|sign in|secure\w*)\b", re.IGNORECASE)
_AUDIT_REQUIREMENT = re.compile(r"\b(audit\w*|record\w*|log\w*)\b", re.IGNORECASE)

def synthesize(reqs: list[Requirement], components: list[Component]) -> Architecture:
    rels = []
    related_by_requirement = {
        requirement.id: [component for component in components if requirement.id in component.requirements]
        for requirement in reqs
    }
    for requirement in reqs:
        related = related_by_requirement[requirement.id]
        if requirement.type != "functional":
            if requirement.type == "non_functional":
                _add_audit_relationship(rels, requirement, related)
            continue

        actor = _external_actor(requirement.text)
        if actor:
            for component in related:
                _append_relationship(rels, Relationship(
                    source=f"External: {actor}",
                    target=component.name,
                    kind="request",
                    rationale=f"{requirement.id} identifies {actor} as requesting this capability: {requirement.text}",
                ))

        if _AUTH_REQUIREMENT.search(requirement.text):
            auth_components = [component for component in related if "authentication" in component.name.casefold()]
            for auth_component in auth_components:
                for consumer in related:
                    if consumer is auth_component:
                        continue
                    _append_relationship(rels, Relationship(
                        source=consumer.name,
                        target=auth_component.name,
                        kind="depends_on",
                        rationale=(
                            f"{requirement.id} requires {consumer.name} to depend on "
                            f"{auth_component.name} for authentication: {requirement.text}"
                        ),
                    ))

        if _TRIGGER_CLAUSE.search(requirement.text):
            event = _triggered_event_relationship(requirement, related)
            if event:
                _append_relationship(rels, event)

    patterns = ["Layered Architecture"]
    if any(relationship.kind == "event" for relationship in rels):
        patterns.append("Event-Driven Architecture")
    recommended_patterns = ["Strategy", "Facade", "Factory Method", "Observer", "Chain of Responsibility", "Repository"]
    return Architecture(
        style="Layered + Pipeline-based architecture",
        components=components,
        relationships=rels,
        patterns=patterns,
        recommended_patterns=recommended_patterns,
    )


def _external_actor(text: str) -> str:
    match = _AS_ACTOR.match(text.strip()) or _MODAL_SUBJECT.match(text.strip())
    if not match:
        return ""
    actor = " ".join(match.group(1).split())
    return "" if actor.casefold() in _SYSTEM_ACTORS else actor


def _triggered_event_relationship(
    requirement: Requirement,
    related: list[Component],
) -> Relationship | None:
    trigger = _TRIGGER_CLAUSE.search(requirement.text)
    if not trigger:
        return None
    action_terms = _meaningful_terms(requirement.text[:trigger.start()])
    trigger_terms = _meaningful_terms(requirement.text[trigger.end():])
    if not action_terms or not trigger_terms:
        return None
    receiver = _best_component_match(related, action_terms)
    source = _best_component_match(related, trigger_terms, exclude=receiver)
    if not receiver or not source:
        return None
    return Relationship(
        source=source.name,
        target=receiver.name,
        kind="event",
        rationale=(
            f"{requirement.id} explicitly states that {trigger.group(0).casefold()} "
            f"activity in {source.name} triggers {receiver.name}: {requirement.text}"
        ),
    )


def _add_audit_relationship(
    relationships: list[Relationship],
    requirement: Requirement,
    related: list[Component],
) -> None:
    if not _AUDIT_REQUIREMENT.search(requirement.text):
        return
    audit = next((component for component in related if "audit" in component.name.casefold()), None)
    if not audit:
        return
    source = _best_component_match(
        [component for component in related if component is not audit],
        _meaningful_terms(requirement.text),
    )
    if source:
        _append_relationship(relationships, Relationship(
            source=source.name,
            target=audit.name,
            kind="audit-write",
            rationale=f"{requirement.id} requires {source.name} activity to be recorded by {audit.name}: {requirement.text}",
        ))


def _best_component_match(
    candidates: list[Component],
    terms: set[str],
    *,
    exclude: Component | None = None,
) -> Component | None:
    scored = []
    for component in candidates:
        if component is exclude:
            continue
        score = len(_meaningful_terms(f"{component.name} {component.responsibility}") & terms)
        if score:
            scored.append((score, component))
    if not scored:
        return None
    highest = max(score for score, _ in scored)
    winners = [component for score, component in scored if score == highest]
    return winners[0] if len(winners) == 1 else None


def _meaningful_terms(text: str) -> set[str]:
    stop_words = {
        "a", "an", "and", "as", "at", "be", "by", "for", "from", "in", "into", "is", "it", "of", "on", "or", "the", "to", "with",
        "system", "shall", "should", "must", "can", "will", "may", "when", "after", "once", "upon",
        "every", "all", "this", "that", "these", "those", "their", "user", "users",
    }
    return set(re.findall(r"[a-z0-9]+", text.casefold())) - stop_words


def _append_relationship(relationships: list[Relationship], candidate: Relationship) -> None:
    identity = (candidate.source.casefold(), candidate.target.casefold(), candidate.kind.casefold())
    if not any(
        (item.source.casefold(), item.target.casefold(), item.kind.casefold()) == identity
        for item in relationships
    ):
        relationships.append(candidate)
