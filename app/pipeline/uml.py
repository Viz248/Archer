from app.models import Architecture, Requirement
import re


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", text).strip("_") or "Node"


def use_case(reqs: list[Requirement]) -> str:
    lines = [
        "flowchart LR",
        "    A[Software Architect / Developer] --> SYS((Requirements to Architecture System))",
        "    R[Reviewer] --> SYS",
    ]
    for i, r in enumerate(reqs, 1):
        label = r.text.replace('"', "'")[:70]
        lines.append(f'    SYS --> U{i}["{r.id}: {label}"]')
    return "\n".join(lines)


def class_diagram(arch: Architecture) -> str:
    lines = [
        "classDiagram",
        "class Requirement",
        "class Component",
        "class Architecture",
        "class TraceLink",
        "class PipelineStage",
        "class DiagramGenerator",
        "class ReportExporter",
        "Architecture o-- Component",
        "Architecture --> Requirement",
        "TraceLink --> Requirement",
        "TraceLink --> Component",
        "PipelineStage --> Architecture",
        "Architecture --> DiagramGenerator",
        "Architecture --> ReportExporter",
    ]
    for c in arch.components:
        safe = _safe(c.name)
        lines += [f"class {safe}", f"Component <|-- {safe}"]
    return "\n".join(lines)


def sequence(arch: Architecture) -> str:
    lines = [
        "sequenceDiagram",
        "actor User",
        "participant API",
        "participant Parser",
        "participant Extractor",
        "participant Synthesizer",
        "participant Tracer",
        "participant UML",
        "participant Report",
        "User->>API: Submit requirements",
        "API->>Parser: Parse + classify",
        "Parser-->>API: Structured requirements",
        "API->>Extractor: Extract components",
        "Extractor-->>API: Components",
        "API->>Synthesizer: Synthesize architecture",
        "Synthesizer-->>API: Architecture",
        "API->>Tracer: Reflect + build trace links",
        "Tracer-->>API: Rationale + warnings",
        "API->>UML: Generate diagrams",
        "UML-->>API: Mermaid specs",
        "API->>Report: Build report",
        "Report-->>User: Architecture + trace + diagrams",
    ]
    return "\n".join(lines)


def activity() -> str:
    return """flowchart TD
    A([Start]) --> B[Upload / paste requirements]
    B --> C[Parse and classify requirements]
    C --> D[Extract components]
    D --> E{Ambiguous requirements?}
    E -- Yes --> F[Flag for clarification]
    F --> C
    E -- No --> G[Synthesize architecture]
    G --> H[Reflection + traceability check]
    H --> I[Generate UML diagrams]
    I --> J[Generate report]
    J --> K{Reviewer changes?}
    K -- Yes --> G
    K -- No --> L([Approved output])"""
