from dataclasses import dataclass, field, asdict
from typing import Literal

ReqType = Literal["functional", "non_functional", "ambiguous"]

@dataclass
class Requirement:
    id: str
    text: str
    type: ReqType
    confidence: float

@dataclass
class Component:
    id: str
    name: str
    responsibility: str
    requirements: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)

@dataclass
class Relationship:
    source: str
    target: str
    kind: str
    rationale: str

@dataclass
class Architecture:
    style: str
    components: list[Component]
    relationships: list[Relationship]
    patterns: list[str]

@dataclass
class TraceLink:
    requirement_id: str
    architectural_element: str
    decision: str
    rationale: str
    confidence: float

@dataclass
class PipelineResult:
    run_id: str
    requirements: list[Requirement]
    architecture: Architecture
    trace_links: list[TraceLink]
    uml: dict[str, str]
    report_markdown: str
    warnings: list[str] = field(default_factory=list)
    mode: str = "deterministic-fallback"
    ai_stages: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
