from dataclasses import dataclass, field, asdict
import hashlib
import json
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
    finding_ids: list[str] = field(default_factory=list)

@dataclass
class EvaluationFinding:
    code: str
    severity: Literal["warning", "error"]
    subject: str
    requirement_ids: list[str]
    message: str
    impact: str
    action: str
    finding_id: str = ""

    def __post_init__(self):
        if self.finding_id:
            return
        normalize = lambda value: " ".join(value.casefold().split())
        identity = [
            normalize(self.code),
            normalize(self.severity),
            sorted(normalize(item) for item in self.requirement_ids),
            normalize(self.subject),
            normalize(self.message),
            normalize(self.impact),
            normalize(self.action),
        ]
        digest = hashlib.sha256(
            json.dumps(identity, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12].upper()
        self.finding_id = f"EV-{digest}"

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
