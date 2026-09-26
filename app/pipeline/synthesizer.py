from app.models import Architecture, Component, Relationship, Requirement

def synthesize(reqs: list[Requirement], components: list[Component]) -> Architecture:
    names = {c.name for c in components}
    rels = []
    # Client/API entrypoint is always useful for a high-level architecture.
    for c in components:
        rels.append(Relationship(source="Client", target=c.name, kind="request", rationale="Client submits or consumes the capability."))
    ordered = components
    for a, b in zip(ordered, ordered[1:]):
        rels.append(Relationship(source=a.name, target=b.name, kind="service-call", rationale="Pipeline/service dependency inferred from related capabilities."))
    if "Authentication Service" in names:
        for c in components:
            if c.name != "Authentication Service":
                rels.append(Relationship(source=c.name, target="Authentication Service", kind="auth", rationale="Protects service access using the authentication requirement."))
    if "Notification Service" in names:
        rels.append(Relationship(source="Order Service" if "Order Service" in names else components[0].name, target="Notification Service", kind="event", rationale="Business events can trigger user notifications."))
    patterns = ["Layered Architecture", "Pipeline / Pipes and Filters", "Strategy", "Facade", "Factory Method", "Observer", "Chain of Responsibility", "Repository"]
    return Architecture(style="Layered + Pipeline-based architecture", components=components, relationships=rels, patterns=patterns)
