from app.models import PipelineResult
from .evaluator import finding_warning


_DIAGRAM_LABELS = {
    "architecture": "System Architecture / Components",
    "use_case": "Use-Case Representation",
    "sequence": "System Sequence",
    "activity": "System Activity / Workflow",
    "class": "Domain Class Diagram",
}


def build_report(result: PipelineResult) -> str:
    lines = [
        "# AI Assisted Requirements to Architecture Synthesis Report", "",
        f"**Run ID:** `{result.run_id}`", f"**Mode:** `{result.mode}`", "",
        "## 1. Requirements", "",
        "| ID | Type | Confidence | Requirement |", "|---|---|---:|---|",
    ]
    for r in result.requirements:
        lines.append(f"| {r.id} | {r.type} | {r.confidence:.2f} | {r.text.replace('|','/')} |")
    lines += ["", "## 2. Synthesized Architecture", "", f"**Style:** {result.architecture.style}", ""]
    for c in result.architecture.components:
        lines += [f"### {c.name}", c.responsibility, f"- Requirements: {', '.join(c.requirements) or 'cross-cutting'}", f"- Technologies: {', '.join(c.technologies)}", ""]
    lines += ["## 3. Architectural Relationships", ""]
    for rel in result.architecture.relationships:
        lines.append(f"- **{rel.source} → {rel.target}** ({rel.kind}) — {rel.rationale}")
    lines += ["", "## 4. Traceability / Rationale", "", "| Requirement | Element | Decision | Rationale |", "|---|---|---|---|"]
    for t in result.trace_links:
        lines.append(f"| {t.requirement_id} | {t.architectural_element} | {t.decision} | {t.rationale} |")
    lines += ["", "## 5. Applied Design Patterns", ""]
    lines += [f"- {p}" for p in result.architecture.patterns] or ["- None declared."]
    lines += ["", "### Recommended, Not Yet Applied", ""]
    lines += [f"- {p}" for p in result.architecture.recommended_patterns] or ["- None."]
    lines += ["", "## 6. AI/LLM Pipeline Execution", ""] + [f"- {x}" for x in result.ai_stages]
    lines += [
        "", "## 7. Evaluation", "",
        "Requirement traceability is a mapping, not proof of satisfaction.", "",
        "| Requirement | Status | Evidence | Findings / unresolved gaps |",
        "|---|---|---|---|",
    ]
    for assessment in result.requirement_assessments:
        assessment_refs = (
            ", ".join(assessment.finding_ids)
            if assessment.finding_ids
            else "; ".join(assessment.gaps) or "None recorded"
        )
        lines.append(
            f"| {_cell(assessment.requirement_id)} | {_cell(assessment.status)} | "
            f"{_cell('; '.join(assessment.evidence) or 'No evidence recorded')} | "
            f"{_cell(assessment_refs)} |"
        )
    if result.evaluation_findings:
        lines += [
            "", "### Actionable Findings", "",
            "| Finding ID | Severity | Subject | Requirements | Finding | Why it matters | Action |",
            "|---|---|---|---|---|---|---|",
        ]
        for finding in result.evaluation_findings:
            lines.append(
                f"| {_cell(finding.finding_id)} | {_cell(finding.severity)} | {_cell(finding.subject)} | "
                f"{_cell(', '.join(finding.requirement_ids) or '—')} | {_cell(finding.message)} | "
                f"{_cell(finding.impact)} | {_cell(finding.action)} |"
            )
    else:
        lines += ["", "No deterministic consistency findings."]
    finding_warnings = {finding_warning(item) for item in result.evaluation_findings}
    pipeline_warnings = [warning for warning in result.warnings if warning not in finding_warnings]
    if pipeline_warnings:
        lines += ["", "### Pipeline Warnings", ""] + [f"- {warning}" for warning in pipeline_warnings]
    lines += ["", "## 8. Generated Target-System Diagrams", ""]
    for key, label in _DIAGRAM_LABELS.items():
        source = result.uml.get(key, "")
        status = result.diagram_status.get(key, "unavailable: No diagram status was provided.")
        lines += [f"### {label}", ""]
        if source:
            lines += ["```mermaid", source, "```", ""]
            if status != "available":
                lines.append(f"Diagram note: {_cell(status)}")
        else:
            lines.append(f"Unavailable: {_cell(status.removeprefix('unavailable: ').strip())}")
        lines.append("")
    lines += ["## 9. Archer Internal Workflow (Developer Documentation)", ""]
    for key, source in result.internal_workflow_diagrams.items():
        lines += [f"### {_cell(key.replace('_', ' ').title())}", "", "```mermaid", source, "```", ""]
    lines += ["## 10. AI/LLM Design Patterns", "", "- Prompt chaining", "- Tool use / function calling", "- Structured output generation", "- Routing", "- Reflection / self-critique", "- Evaluator-optimizer", "", "This demo records generated artifacts and traceability. The supplied project document defines accuracy, repeated-run consistency, and manual design-time reduction as evaluation goals, but provides no measured experimental results. Therefore this demo does not fabricate evaluation values."]
    return "\n".join(lines)


def _cell(value: str) -> str:
    return str(value).replace("|", "/").replace("\n", " ").strip()
