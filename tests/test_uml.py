import re

from app.models import Architecture, Component, Relationship, Requirement
from app.pipeline.report import build_report
from app.pipeline.uml import generate_diagrams, internal_workflow_diagrams
from app.pipeline.engine import run_pipeline


def _component(name, requirement_ids, responsibility="Handles the capability."):
    return Component(
        id=f"COMP-{name}",
        name=name,
        responsibility=responsibility,
        requirements=requirement_ids,
        technologies=[],
    )


def _requirement(requirement_id, text, kind="functional"):
    return Requirement(id=requirement_id, text=text, type=kind, confidence=0.9)


def _architecture(components, relationships=()):
    return Architecture(
        style="Service architecture",
        components=components,
        relationships=list(relationships),
        patterns=[],
    )


def test_component_diagram_uses_architecture_components_and_relationships():
    components = [
        _component("Order Management Service", ["REQ-001"], "Creates and tracks orders."),
        _component("Payment Service", ["REQ-001"], "Processes payments."),
    ]
    architecture = _architecture(components, [
        Relationship("Order Management Service", "Payment Service", "service-call", "Order requests payment."),
    ])

    diagrams, status = generate_diagrams([_requirement("REQ-001", "Users place orders.")], architecture)
    source = diagrams["architecture"]

    assert status["architecture"] == "available"
    assert 'C0["Order Management Service"]' in source
    assert 'C1["Payment Service"]' in source
    assert "Creates and tracks orders" not in source
    assert "C0 -->|service-call| C1" in source


def test_changed_requirements_and_architecture_change_target_diagrams():
    first_requirements = [_requirement("REQ-001", "Customers can submit a booking.")]
    first_architecture = _architecture([_component("Booking Service", ["REQ-001"])])
    second_requirements = [_requirement("REQ-002", "Members can reserve a workspace.")]
    second_architecture = _architecture([_component("Workspace Service", ["REQ-002"])])

    first, _ = generate_diagrams(first_requirements, first_architecture)
    second, _ = generate_diagrams(second_requirements, second_architecture)

    assert first["architecture"] != second["architecture"]
    assert first["use_case"] != second["use_case"]


def test_target_diagrams_exclude_archer_internal_workflow_and_classes():
    requirement = _requirement("REQ-001", "Customers can book a workspace.")
    architecture = _architecture([_component("Workspace Booking Service", ["REQ-001"])])
    diagrams, status = generate_diagrams([requirement], architecture)
    target_source = "\n".join(diagrams.values())
    internal = internal_workflow_diagrams()["workflow"]

    assert "Workspace Booking Service" in target_source
    for internal_name in ("Requirement", "TraceLink", "PipelineStage", "DiagramGenerator", "ReportExporter"):
        assert internal_name not in target_source
    assert diagrams["class"] == ""
    assert status["class"].startswith("unavailable:")
    assert "Architecture synthesis" in internal
    assert "Report generation" in internal


def test_component_relationship_direction_and_type_are_preserved():
    architecture = _architecture(
        [_component("Publisher", ["REQ-001"]), _component("Subscriber", ["REQ-001"])],
        [Relationship("Publisher", "Subscriber", "event-publish", "Publishes state change.")],
    )
    diagrams, _ = generate_diagrams([_requirement("REQ-001", "A publisher sends an event.")], architecture)

    assert "C0 -->|event-publish| C1" in diagrams["architecture"]
    assert "C1 -->|event-publish| C0" not in diagrams["architecture"]


def test_invalid_relationship_endpoints_are_not_invented_and_are_reported():
    architecture = _architecture(
        [_component("Order Service", ["REQ-001"])],
        [Relationship("Order Service", "Missing Service", "service-call", "Calls missing service.")],
    )

    diagrams, status = generate_diagrams([_requirement("REQ-001", "Users can place orders.")], architecture)

    assert "Missing Service" not in diagrams["architecture"]
    assert "-->" not in diagrams["architecture"]
    assert "omitted 1 relationship" in status["architecture"]


def test_insufficient_workflow_information_does_not_create_sequence_or_activity():
    requirements = [_requirement("REQ-001", "Users can register an account.")]
    architecture = _architecture([
        _component("Registration Service", ["REQ-001"]),
        _component("Profile Service", ["REQ-001"]),
    ])

    diagrams, status = generate_diagrams(requirements, architecture)

    assert diagrams["sequence"] == ""
    assert diagrams["activity"] == ""
    assert status["sequence"].startswith("unavailable:")
    assert status["activity"].startswith("unavailable:")


def test_dependency_edges_without_requirement_order_do_not_create_workflow_diagrams():
    requirement = _requirement("REQ-009", "Users can register an account.")
    architecture = _architecture(
        [_component("Registration Service", ["REQ-009"]), _component("Profile Service", ["REQ-009"])],
        [Relationship("Registration Service", "Profile Service", "service-call", "Registration depends on profiles.")],
    )

    diagrams, status = generate_diagrams([requirement], architecture)

    assert diagrams["sequence"] == ""
    assert diagrams["activity"] == ""
    assert status["sequence"].startswith("unavailable:")
    assert status["activity"].startswith("unavailable:")


def test_sequence_and_activity_follow_explicit_requirement_cue_and_architecture_path():
    requirements = [_requirement(
        "REQ-001", "The system sends a notification when a booking is confirmed."
    )]
    architecture = _architecture(
        [
            _component("Booking Service", ["REQ-001"]),
            _component("Notification Service", ["REQ-001"]),
        ],
        [Relationship("Booking Service", "Notification Service", "event-publish", "Sends booking event.")],
    )

    diagrams, status = generate_diagrams(requirements, architecture)

    assert status["sequence"] == "available"
    assert status["activity"] == "available"
    assert 'P0 as "Booking Service"' in diagrams["sequence"]
    assert "P0-)P1: Sends booking event." in diagrams["sequence"]
    assert 'S0 -->|Sends booking event.| S1' in diagrams["activity"]

def test_sequence_excludes_mapped_components_unrelated_to_scenario_text():
    requirement = _requirement("REQ-001",
        "The system sends an email notification when an order is placed."
    )
    architecture = _architecture(
        [
            _component("Order Service", ["REQ-001"], "Creates and manages orders."),
            _component("Notification Service", ["REQ-001"], "Sends email notifications."),
            _component("AI Inference Service", ["REQ-001"], "Runs model inference."),
        ],
        [
            Relationship("Order Service", "Notification Service", "service-call", "Pipeline dependency."),
            Relationship("Order Service", "Notification Service", "event-publish", "Order events trigger notification delivery."),
            Relationship("Notification Service", "AI Inference Service", "service-call", "Invokes model inference."),
        ],
    )

    diagrams, _ = generate_diagrams([requirement], architecture)

    assert "Order Service" in diagrams["sequence"]
    assert "Notification Service" in diagrams["sequence"]
    assert "AI Inference Service" not in diagrams["sequence"]
    assert "P0-)P1: Order events trigger notification delivery." in diagrams["sequence"]


def test_component_names_with_mermaid_special_characters_are_escaped():
    unusual_name = 'Order ]]> "Fast | Safe" #1'
    architecture = _architecture([_component(unusual_name, ["REQ-001"])])
    diagrams, _ = generate_diagrams([_requirement("REQ-001", "Users can order items.")], architecture)

    source = diagrams["architecture"]
    assert unusual_name not in source
    assert "#93;" in source
    assert "#quot;" in source
    assert "#124;" in source
    assert "#35;" in source
    assert 'C0["' in source


def test_relationship_labels_with_mermaid_delimiters_are_escaped():
    architecture = _architecture(
        [_component("Source", ["REQ-001"]), _component("Target", ["REQ-001"])],
        [Relationship("Source", "Target", "event | publish --> target", "Preserve direction.")],
    )

    diagrams, _ = generate_diagrams([_requirement("REQ-001", "A source publishes an event.")], architecture)
    source = diagrams["architecture"]

    assert "C0 -->|event #124; publish --#gt; target| C1" in source
    assert "event | publish --> target" not in source


def test_use_case_representation_excludes_nonfunctional_and_ambiguous_requirements():
    requirements = [
        _requirement("REQ-001", "As a customer, I want to submit a booking."),
        _requirement("REQ-002", "The system shall provide 99.9% uptime.", "non_functional"),
        _requirement("REQ-003", "Make it fast.", "ambiguous"),
    ]
    diagrams, _ = generate_diagrams(requirements, _architecture([]))

    assert "use-case representation" in diagrams["use_case"].casefold()
    assert "customer" in diagrams["use_case"].casefold()
    assert "REQ-001" in diagrams["use_case"]
    assert "REQ-002" not in diagrams["use_case"]
    assert "REQ-003" not in diagrams["use_case"]
    assert "Software Architect" not in diagrams["use_case"]
    assert "Reviewer" not in diagrams["use_case"]
    use_case_ids = set(re.findall(r"\b(U\d+)\s*\(", diagrams["use_case"]))
    associated_ids = set(re.findall(r"\bA\d+\s+-->\s+(U\d+)\b", diagrams["use_case"]))
    assert use_case_ids == associated_ids


def test_system_trigger_notification_use_case_is_associated_to_its_actor():
    requirement = _requirement(
        "REQ-007", "The system shall send an email notification when an order is placed."
    )

    diagrams, _ = generate_diagrams([requirement], _architecture([]))
    source = diagrams["use_case"]

    assert 'A0(["System trigger"])' in source
    assert "A0 --> U0" in source
    assert "REQ-007" in source


def test_every_use_case_has_an_explicit_actor_or_system_trigger_association():
    requirements = [
        _requirement("REQ-010", "Users shall place orders."),
        _requirement("REQ-007", "The system shall send an email notification when an order is placed."),
    ]

    diagrams, _ = generate_diagrams(requirements, _architecture([]))
    source = diagrams["use_case"]

    assert 'A0(["Users"])' in source
    assert 'A1(["System trigger"])' in source
    assert "A0 --> U0" in source
    assert "A1 --> U1" in source


def test_long_component_and_use_case_labels_are_wrapped_and_escaped():
    long_name = 'International Payment "Gateway" Service - Region One'
    requirement = _requirement(
        "REQ-008", "As a payments administrator, I want to reconcile international transactions."
    )
    architecture = _architecture([_component(long_name, ["REQ-008"])])

    diagrams, _ = generate_diagrams([requirement], architecture)

    assert "<br/>" in diagrams["architecture"]
    assert "<br/>" in diagrams["use_case"]
    assert long_name not in diagrams["architecture"]
    assert "#quot;" in diagrams["architecture"]


def test_mermaid_sources_follow_supported_diagram_grammar_for_representative_input():
    requirements = [_requirement("REQ-001", "A client sends a booking then receives a confirmation.")]
    architecture = _architecture(
        [_component("Booking Service", ["REQ-001"]), _component("Confirmation Service", ["REQ-001"])],
        [Relationship("Booking Service", "Confirmation Service", "service-call", "Creates confirmation.")],
    )
    diagrams, _ = generate_diagrams(requirements, architecture)

    assert diagrams["architecture"].startswith("flowchart TD\n")
    assert re.search(r"^\s*C\d+\s+-->\|[^|]+\|\s+C\d+$", diagrams["architecture"], re.MULTILINE)
    assert diagrams["use_case"].startswith("flowchart LR\n")
    assert "client" in diagrams["use_case"].casefold()
    assert diagrams["sequence"].startswith("sequenceDiagram\n")
    assert re.search(r"^\s*P\d+->P\d+: .+$", diagrams["sequence"], re.MULTILINE)
    assert diagrams["activity"].startswith("flowchart TD\n")
    assert "Archer" not in diagrams["architecture"]


def test_markdown_report_embeds_exact_generated_diagram_sources():
    result = run_pipeline(
        "Customers can submit a booking.\nThe system sends a confirmation when a booking is accepted."
    )

    for diagram_name in ("architecture", "use_case"):
        source = result.uml[diagram_name]
        assert source
        assert f"```mermaid\n{source}\n```" in result.report_markdown
    assert result.internal_workflow_diagrams["workflow"] in result.report_markdown
    assert "Archer Internal Workflow (Developer Documentation)" in result.report_markdown


def test_markdown_report_explains_unavailable_target_diagrams():
    result = run_pipeline("Users can register an account.")

    assert "### System Sequence" in result.report_markdown
    assert "### System Activity / Workflow" in result.report_markdown
    assert "### Domain Class Diagram" in result.report_markdown
    assert "Unavailable: No explicit requirement-supported interaction order" in result.report_markdown
    assert "Unavailable: Structured input contains services/components" in result.report_markdown