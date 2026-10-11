from app.models import Component, Requirement
from app.pipeline.synthesizer import synthesize
from app.pipeline.uml import architecture_diagram


def _requirement(requirement_id, text, kind="functional"):
    return Requirement(requirement_id, text, kind, 0.9)


def _component(name, requirement_ids):
    return Component(
        id=f"COMP-{name}",
        name=name,
        responsibility=f"Supports {name} capability.",
        requirements=requirement_ids,
        technologies=[],
    )


def test_payment_components_receive_external_requests_not_invented_service_dependencies():
    requirements = [_requirement("REQ-001", "Customers can create orders and pay online.")]
    components = [
        _component("Order Service", ["REQ-001"]),
        _component("Payment Service", ["REQ-001"]),
    ]

    architecture = synthesize(requirements, components)

    assert any(
        relationship.source == "External: Customers"
        and relationship.target == "Order Service"
        and relationship.kind == "request"
        for relationship in architecture.relationships
    )
    assert any(
        relationship.source == "External: Customers"
        and relationship.target == "Payment Service"
        and relationship.kind == "request"
        for relationship in architecture.relationships
    )
    assert not any(relationship.kind == "service-call" for relationship in architecture.relationships)
    diagram, _ = architecture_diagram(architecture)
    assert 'X0(["Customers"])' in diagram
    assert "External: External" not in diagram


def test_notification_event_and_pattern_require_an_explicit_requirement_trigger():
    components = [
        _component("Order Service", ["REQ-001"]),
        _component("Notification Service", ["REQ-001"]),
    ]
    event_architecture = synthesize(
        [_requirement("REQ-001", "The system sends an email notification when an order is placed.")],
        components,
    )

    event = next(r for r in event_architecture.relationships if r.kind == "event")
    assert event.source == "Order Service"
    assert event.target == "Notification Service"
    assert "REQ-001" in event.rationale
    assert "Event-Driven Architecture" in event_architecture.patterns

    no_trigger_architecture = synthesize(
        [_requirement("REQ-002", "The system sends email notifications.")],
        [
            _component("Order Service", ["REQ-002"]),
            _component("Notification Service", ["REQ-002"]),
        ],
    )
    assert not any(r.kind == "event" for r in no_trigger_architecture.relationships)
    assert "Event-Driven Architecture" not in no_trigger_architecture.patterns


def test_auditing_relationship_means_source_action_is_recorded_by_audit_target():
    requirement = _requirement("REQ-004", "The system shall audit every order state change.", "non_functional")
    architecture = synthesize(
        [requirement],
        [
            _component("Order Service", ["REQ-004"]),
            _component("Audit Service", ["REQ-004"]),
        ],
    )

    audit = next(r for r in architecture.relationships if r.kind == "audit-write")

    assert audit.source == "Order Service"
    assert audit.target == "Audit Service"
    assert "REQ-004" in audit.rationale


def test_authentication_dependency_points_from_consumer_to_auth_provider():
    requirement = _requirement("REQ-005", "Users shall sign in securely.")
    architecture = synthesize(
        [requirement],
        [
            _component("User Service", ["REQ-005"]),
            _component("Authentication Service", ["REQ-005"]),
        ],
    )

    dependency = next(r for r in architecture.relationships if r.kind == "depends_on")

    assert dependency.source == "User Service"
    assert dependency.target == "Authentication Service"
    assert "depend on" in dependency.rationale.casefold()


def test_availability_infrastructure_is_not_sequentially_wired_to_business_components():
    architecture = synthesize(
        [_requirement("REQ-006", "The system shall support high availability.", "non_functional")],
        [
            _component("Order Service", ["REQ-006"]),
            _component("High Availability Infrastructure", ["REQ-006"]),
        ],
    )

    assert not any(
        relationship.source == "Order Service"
        and relationship.target == "High Availability Infrastructure"
        and relationship.kind in {"service-call", "depends_on"}
        for relationship in architecture.relationships
    )