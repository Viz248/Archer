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
    recommended_patterns: list[str] = field(default_factory=list)

@dataclass
class TraceLink:
    requirement_id: str
    architectural_element: str
    decision: str
    rationale: str
    confidence: float

@dataclass
class RequirementAssessment:
    requirement_id: str
    status: Literal["mapped", "satisfied", "partially_satisfied", "unresolved"]
    evidence: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

@dataclass
class EvaluationFinding:
    code: str
    severity: Literal["warning", "error"]
    subject: str
    requirement_ids: list[str]
    message: str
    impact: str
    action: str

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
    requirement_assessments: list[RequirementAssessment] = field(default_factory=list)
    evaluation_findings: list[EvaluationFinding] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)
