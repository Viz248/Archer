from types import SimpleNamespace

import pytest

from app.models import Architecture, Component, Relationship, Requirement, TraceLink
from app.pipeline.evaluator import _dedupe_findings, _finding, evaluate_architecture


def _requirement(text="Users can place orders.", requirement_id="REQ-001", kind="functional"):
    return Requirement(id=requirement_id, text=text, type=kind, confidence=0.9)


def _component(name="Order Service", requirements=None, responsibility="Creates and manages orders."):
    return Component(
        id=f"COMP-{name}",
        name=name,
        responsibility=responsibility,
        requirements=requirements or ["REQ-001"],
    )


def _architecture(components=None, relationships=None, patterns=None, recommended_patterns=None):
    return Architecture(
        style="Layered",
        components=components or [_component()],
        relationships=relationships or [],
        patterns=patterns or ["Layered Architecture"],
        recommended_patterns=recommended_patterns or [],
    )


def _trace(element="Order Service", requirement_id="REQ-001"):
    return [TraceLink(
        requirement_id=requirement_id,
        architectural_element=element,
        decision=f"Use {element}",
        rationale="The component owns the requested capability.",
        confidence=0.9,
    )]


def test_applied_api_gateway_without_component_or_relationship_is_flagged():
    _, findings = evaluate_architecture(
        [_requirement()],
        _architecture(patterns=["API Gateway"]),
        _trace(),
    )

    assert any(f.code == "applied_pattern_unrepresented" for f in findings)


def test_recommended_unimplemented_circuit_breaker_is_not_reported_as_applied():
    _, findings = evaluate_architecture(
        [_requirement()],
        _architecture(recommended_patterns=["Circuit Breaker"]),
        _trace(),
    )

    assert not any("pattern" in f.code for f in findings)


@pytest.mark.parametrize(
    "pattern",
    ["Circuit Breaker (recommended)", "Circuit Breaker - recommended"],
)
def test_suffix_recommended_pattern_is_not_reported_as_applied(pattern):
    _, findings = evaluate_architecture(
        [_requirement()],
        _architecture(patterns=[pattern]),
        _trace(),
    )

    assert not any("pattern" in f.code for f in findings)


def test_trace_link_does_not_override_partial_satisfaction_assessment():
    assessment = SimpleNamespace(
        requirement_id="REQ-001",
        status="partially_satisfied",
        evidence="Order Service accepts orders.",
        gaps=["No cancellation path is defined."],
    )
    assessments, findings = evaluate_architecture(
        [_requirement("Users can place and cancel orders.")],
        _architecture(),
        _trace(),
        [assessment],
    )

    assert assessments[0].status == "partially_satisfied"
    assert "No cancellation path is defined." in assessments[0].gaps
    assert any(f.code == "requirement_partial" for f in findings)
    assert {finding.finding_id for finding in findings if "REQ-001" in finding.requirement_ids}.issubset(
        set(assessments[0].finding_ids)
    )


def test_satisfied_status_with_reported_gaps_is_downgraded_to_partial():
    assessment = SimpleNamespace(
        requirement_id="REQ-001",
        status="satisfied",
        evidence="Order Service creates orders.",
        gaps=["Cancellation behavior is unspecified."],
    )

    assessments, findings = evaluate_architecture(
        [_requirement()], _architecture(), _trace(), [assessment]
    )

    assert assessments[0].status == "partially_satisfied"
    assert "Cancellation behavior is unspecified." in assessments[0].gaps
    assert any(f.code == "requirement_partial" for f in findings)


def test_satisfied_assessment_without_evidence_is_unresolved():
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [_requirement()], _architecture(), _trace(), [assessment]
    )

    assert assessments[0].status == "unresolved"
    assert any(f.code == "requirement_unresolved" for f in findings)


def test_unmapped_requirement_preserves_semantic_assessment_evidence_and_gaps():
    assessment = SimpleNamespace(
        requirement_id="REQ-001",
        status="partially_satisfied",
        evidence="No architecture element addresses cancellation.",
        gaps=["Cancellation handling is missing."],
    )

    assessments, findings = evaluate_architecture(
        [_requirement()], _architecture(), [], [assessment]
    )

    assert assessments[0].status == "unresolved"
    assert "No architecture element addresses cancellation." in assessments[0].evidence
    assert "Cancellation handling is missing." in assessments[0].gaps
    assert any(f.code == "requirement_unmapped" for f in findings)


def test_duplicate_requirement_assessments_are_reported():
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Order Service exists.", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [_requirement()], _architecture(), _trace(), [assessment, assessment]
    )

    assert assessments[0].status == "unresolved"
    assert any(f.code == "duplicate_requirement_assessment" for f in findings)


def test_partial_assessment_without_gap_gets_explicit_gap_text():
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="partially_satisfied", evidence="Order Service exists.", gaps=[]
    )

    assessments, _ = evaluate_architecture(
        [_requirement()], _architecture(), _trace(), [assessment]
    )

    assert assessments[0].status == "partially_satisfied"
    assert assessments[0].gaps


def test_relationship_to_nonexistent_component_is_flagged():
    architecture = _architecture(relationships=[
        Relationship("Order Service", "Missing Service", "service-call", "Creates orders."),
    ])

    _, findings = evaluate_architecture([_requirement()], architecture, _trace())

    finding = next(f for f in findings if f.code == "relationship_unknown_component")
    assert "Missing Service" in finding.message
    assert finding.action


def test_malformed_relationship_fields_are_reported_against_schema():
    malformed = [
        (Relationship(12, "Order Service", "service-call", "Calls orders."), "invalid_relationship_endpoint"),
        (Relationship("Order Service", "Client", [], "Returns response."), "invalid_relationship_kind"),
        (Relationship("Order Service", "Client", "request", None), "invalid_relationship_rationale"),
    ]

    for relationship, expected_code in malformed:
        _, findings = evaluate_architecture(
            [_requirement()],
            _architecture(relationships=[relationship]),
            _trace(),
        )
        assert any(f.code == expected_code for f in findings)


def test_suspicious_bidirectional_dependency_is_flagged_but_callback_is_not():
    components = [_component("Order Service"), _component("Payment Service")]
    architecture = _architecture(
        components=components,
        relationships=[
            Relationship("Order Service", "Payment Service", "service-call", "Requests payment."),
            Relationship("Payment Service", "Order Service", "depends_on", "Updates order state."),
        ],
    )
    _, findings = evaluate_architecture([_requirement()], architecture, _trace())
    assert any(f.code == "suspicious_dependency_cycle" for f in findings)

    callback_architecture = _architecture(
        components=components,
        relationships=[
            Relationship("Order Service", "Payment Service", "service-call", "Requests payment."),
            Relationship("Payment Service", "Order Service", "callback", "Returns payment result by callback."),
        ],
    )
    _, callback_findings = evaluate_architecture([_requirement()], callback_architecture, _trace())
    assert not any(f.code == "suspicious_dependency_cycle" for f in callback_findings)


def test_multi_component_cycle_finding_does_not_invent_an_edge_order():
    components = [_component("Alpha"), _component("Beta"), _component("Gamma")]
    architecture = _architecture(
        components=components,
        relationships=[
            Relationship("Alpha", "Gamma", "service-call", "Calls gamma."),
            Relationship("Gamma", "Beta", "service-call", "Calls beta."),
            Relationship("Beta", "Alpha", "service-call", "Calls alpha."),
        ],
    )

    _, findings = evaluate_architecture([_requirement()], architecture, _trace("Alpha"))

    cycle = next(f for f in findings if f.code == "suspicious_dependency_cycle")
    assert "Alpha, Beta, Gamma" in cycle.message
    assert "Alpha -> Beta" not in cycle.message


def test_event_publish_cycle_is_not_reported_as_service_dependency_cycle():
    components = [
        _component("Order Service"),
        _component("Event Bus"),
        _component("Notification Service"),
    ]
    architecture = _architecture(
        components=components,
        relationships=[
            Relationship("Order Service", "Event Bus", "event-publish", "Publishes OrderCreated."),
            Relationship("Event Bus", "Notification Service", "event-delivery", "Delivers OrderCreated."),
            Relationship("Notification Service", "Event Bus", "event-publish", "Publishes NotificationSent."),
            Relationship("Event Bus", "Order Service", "event-delivery", "Delivers NotificationSent."),
        ],
    )

    _, findings = evaluate_architecture([_requirement()], architecture, _trace())

    assert not any(f.code == "suspicious_dependency_cycle" for f in findings)


def test_synchronous_request_response_is_not_reported_as_dependency_cycle():
    architecture = _architecture(
        components=[_component("Order Service"), _component("Payment Service")],
        relationships=[
            Relationship("Order Service", "Payment Service", "synchronous-request", "Order requests payment."),
            Relationship("Payment Service", "Order Service", "synchronous-response", "Payment returns the result."),
        ],
    )

    _, findings = evaluate_architecture([_requirement()], architecture, _trace())

    assert not any(f.code == "suspicious_dependency_cycle" for f in findings)


def test_high_availability_name_without_mechanism_is_partial():
    requirement = _requirement(
        "The system shall support high availability.",
        kind="non_functional",
    )
    architecture = _architecture(components=[
        _component("High Availability Infrastructure", responsibility="Coordinates system operations."),
    ])
    trace = _trace("High Availability Infrastructure")
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Infrastructure component is present.", gaps=[]
    )

    assessments, findings = evaluate_architecture([requirement], architecture, trace, [assessment])

    assert assessments[0].status == "partially_satisfied"
    assert any(f.code == "availability_mechanism_unspecified" for f in findings)


def test_requirement_linked_availability_mechanism_is_accepted():
    requirement = _requirement("The system shall provide 99.95% availability.", kind="non_functional")
    architecture = _architecture(components=[
        _component(
            "Order Service",
            responsibility="Maintains two active replicas with health checks and automatic failover.",
        ),
    ])
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Two active replicas are specified.", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [requirement], architecture, _trace(), [assessment]
    )

    assert assessments[0].status == "satisfied"
    assert not any(f.code == "availability_mechanism_unspecified" for f in findings)


@pytest.mark.parametrize(
    "responsibility",
    [
        "No redundancy is configured; failover is only planned.",
        "Failover isn't configured.",
        "Considered failover is not yet deployed.",
    ],
)
def test_negated_or_proposed_availability_keywords_do_not_count_as_mechanisms(responsibility):
    requirement = _requirement("The system shall support high availability.", kind="non_functional")
    architecture = _architecture(components=[
        _component(
            "Availability Service",
            responsibility=responsibility,
        ),
    ])
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Availability Service is present.", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [requirement], architecture, _trace("Availability Service"), [assessment]
    )

    assert assessments[0].status == "partially_satisfied"
    assert assessments[0].gaps
    assert any(f.code == "availability_mechanism_unspecified" for f in findings)

def test_required_future_availability_keywords_do_not_count_as_mechanisms():
    requirement = _requirement("The system shall support high availability.", kind="non_functional")
    architecture = _architecture(components=[
        _component(
            "Availability Service",
            responsibility="The design needs failover and must include health checks.",
        ),
    ])
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Availability Service is present.", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [requirement], architecture, _trace("Availability Service"), [assessment]
    )

    assert assessments[0].status == "partially_satisfied"
    assert any(f.code == "availability_mechanism_unspecified" for f in findings)

def test_valid_trace_link_can_scope_mechanism_when_component_ids_are_incomplete():
    requirement = _requirement("The system shall provide 99.95% availability.", kind="non_functional")
    architecture = _architecture(components=[
        _component(
            "Availability Service",
            requirements=[],
            responsibility="Uses two active replicas and health checks.",
        ),
    ])
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Two active replicas are specified.", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [requirement], architecture, _trace("Availability Service"), [assessment]
    )

    assert assessments[0].status == "satisfied"
    assert not any(f.code == "availability_mechanism_unspecified" for f in findings)


def test_unquantified_availability_requirement_needs_an_acceptance_target():
    requirement = _requirement("The system shall support high availability.", kind="non_functional")
    architecture = _architecture(components=[
        _component(
            "Order Service",
            responsibility="Maintains two active replicas with automatic failover to the standby instance.",
        ),
    ])
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Two active replicas and failover are specified.", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [requirement], architecture, _trace(), [assessment]
    )

    assert assessments[0].status == "partially_satisfied"
    assert any(f.code == "availability_target_unspecified" for f in findings)
    assert not any(f.code == "availability_mechanism_unspecified" for f in findings)


def test_bare_availability_keywords_are_not_concrete_mechanism_evidence():
    requirement = _requirement("The system shall provide 99.95% availability.", kind="non_functional")
    architecture = _architecture(components=[
        _component("Availability Service", responsibility="Provides health checks and failover."),
    ])
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Health checks and failover are named.", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [requirement], architecture, _trace("Availability Service"), [assessment]
    )

    assert assessments[0].status == "partially_satisfied"
    assert any(f.code == "availability_mechanism_unspecified" for f in findings)

def test_clean_architecture_has_no_false_positive_findings():
    architecture = _architecture(relationships=[
        Relationship("Client", "Order Service", "request", "Client submits an order."),
    ])
    assessment = SimpleNamespace(
        requirement_id="REQ-001", status="satisfied", evidence="Order Service creates orders.", gaps=[]
    )

    assessments, findings = evaluate_architecture(
        [_requirement()], architecture, _trace(), [assessment]
    )

    assert assessments[0].status == "satisfied"
    assert findings == []


def test_identical_findings_share_stable_identity_and_deduplicate():
    first = _finding(
        "requirement_clarification", "REQ-001: User Service", ["REQ-001"],
        "Acceptance detail is unspecified.", "The expected behavior cannot be verified.",
        "Clarify the required behavior.",
    )
    repeated = _finding(
        "REQUIREMENT_CLARIFICATION", " req-001:   user service ", ["req-001"],
        "Acceptance detail is   unspecified.", "The expected behavior cannot be verified.",
        "Clarify the required behavior.",
    )

    assert first.finding_id.startswith("EV-")
    assert first.finding_id == repeated.finding_id
    assert len(_dedupe_findings([first, repeated])) == 1


def test_distinct_findings_for_same_requirement_are_preserved():
    policy_gap = _finding(
        "requirement_clarification", "REQ-001: User Service", ["REQ-001"],
        "Order cancellation behavior is unspecified.", "Cancellation acceptance is unclear.",
        "Clarify the required cancellation behavior.",
    )
    storage_gap = _finding(
        "requirement_clarification", "REQ-001: User Service", ["REQ-001"],
        "Order status transition is unspecified.", "Order lifecycle behavior cannot be assessed.",
        "Clarify the allowed order state transitions.",
    )

    distinct = _dedupe_findings([policy_gap, storage_gap])

    assert len(distinct) == 2
    assert distinct[0].finding_id != distinct[1].finding_id


def test_repeated_evidence_sentences_are_removed_across_sources():
    requirement = _requirement()
    component = _component(responsibility="Order Service persists order records.")
    trace = [TraceLink(
        requirement_id="REQ-001",
        architectural_element="Order Service",
        decision="Use Order Service",
        rationale="Order Service persists order records.",
        confidence=0.9,
    )]
    assessment = SimpleNamespace(
        requirement_id="REQ-001",
        status="satisfied",
        evidence="Order Service persists order records. It retries failed writes.",
        gaps=[],
    )

    assessments, _ = evaluate_architecture(
        [requirement], _architecture(components=[component]), trace, [assessment]
    )
    evidence = " ".join(assessments[0].evidence)

    assert evidence.count("Order Service persists order records.") == 1
    assert "It retries failed writes." in evidence


def test_evidence_deduplication_preserves_distinct_component_mappings():
    requirement = _requirement()
    shared_rationale = "Both components validate the order state."
    components = [
        _component("Order Service", responsibility=shared_rationale),
        _component("Audit Service", responsibility=shared_rationale),
    ]
    trace_links = [
        TraceLink("REQ-001", component.name, f"Use {component.name}", shared_rationale, 0.9)
        for component in components
    ]

    assessments, _ = evaluate_architecture(
        [requirement], _architecture(components=components), trace_links
    )

    assert len(assessments[0].evidence) == 2
    assert "Mapped to Order Service" in assessments[0].evidence[0]
    assert "Mapped to Audit Service" in assessments[0].evidence[1]