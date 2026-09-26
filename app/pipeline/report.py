from app.models import PipelineResult

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
    lines += ["", "## 5. Design Patterns", ""] + [f"- {p}" for p in result.architecture.patterns]
    lines += ["", "## 6. AI/LLM Pipeline Execution", ""] + [f"- {x}" for x in result.ai_stages]
    lines += ["", "## 7. Evaluation", ""]
    lines += ["", "## 8. AI/LLM Design Patterns", "", "- Prompt chaining", "- Tool use / function calling", "- Structured output generation", "- Routing", "- Reflection / self-critique", "- Evaluator-optimizer", "", "This demo records generated artifacts and traceability. The supplied project document defines accuracy, repeated-run consistency, and manual design-time reduction as evaluation goals, but provides no measured experimental results. Therefore this demo does not fabricate evaluation values."]
    return "\n".join(lines)
