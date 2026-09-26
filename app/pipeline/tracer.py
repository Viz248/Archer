from app.models import Architecture, Requirement, TraceLink

def build_trace(reqs: list[Requirement], architecture: Architecture) -> list[TraceLink]:
    by_id = {c.id: c for c in architecture.components}
    links = []
    for r in reqs:
        matched = [c for c in architecture.components if r.id in c.requirements]
        if not matched:
            target = architecture.components[0].name if architecture.components else "Architecture"
            links.append(TraceLink(requirement_id=r.id, architectural_element=target, decision="Retained as a cross-cutting or core concern", rationale="No dedicated component was extracted; the requirement is retained in the core architecture.", confidence=0.62))
        else:
            for c in matched:
                links.append(TraceLink(requirement_id=r.id, architectural_element=c.name, decision=f"Create/use {c.name}", rationale=c.responsibility, confidence=0.88))
    return links
