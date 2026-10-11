import uuid
from app.models import PipelineResult
from .parser import parse_requirements
from .components import extract_components
from .synthesizer import synthesize
from .tracer import build_trace
from .uml import generate_diagrams, internal_workflow_diagrams
from .report import build_report
from .llm import is_enabled, run_llm_pipeline
from .evaluator import evaluate_architecture, finding_warning


def run_pipeline(text: str) -> PipelineResult:
    warnings = []
    ai_stages = []
    llm_assessments = None
    mode = "deterministic-fallback"

    if is_enabled():
        try:
            reqs, arch, trace, warnings, ai_stages, llm_assessments = run_llm_pipeline(text)
            mode = "live-llm"
        except Exception as exc:
            # A demo should remain usable if the API is temporarily unavailable.
            warnings = [f"Live LLM pipeline failed; deterministic fallback was used: {exc}"]
            reqs = parse_requirements(text)
            arch = synthesize(reqs, extract_components(reqs))
            trace = build_trace(reqs, arch)
    else:
        reqs = parse_requirements(text)
        arch = synthesize(reqs, extract_components(reqs))
        trace = build_trace(reqs, arch)
        warnings.append("Live LLM mode is not configured. Set LLM_API_KEY to enable model-backed synthesis.")

    requirement_assessments, evaluation_findings = evaluate_architecture(
        reqs,
        arch,
        trace,
        llm_assessments=llm_assessments,
    )
    warnings.extend(finding_warning(finding) for finding in evaluation_findings)
    warnings = _dedupe_warnings(warnings)

    run_id = uuid.uuid4().hex[:10]
    uml, diagram_status = generate_diagrams(reqs, arch)
    result = PipelineResult(
        run_id=run_id,
        requirements=reqs,
        architecture=arch,
        trace_links=trace,
        uml=uml,
        report_markdown="",
        warnings=warnings,
        mode=mode,
        ai_stages=ai_stages,
        requirement_assessments=requirement_assessments,
        evaluation_findings=evaluation_findings,
        diagram_status=diagram_status,
        internal_workflow_diagrams=internal_workflow_diagrams(),
    )
    if any(r.type == "ambiguous" for r in reqs):
        result.warnings.append("One or more requirements were classified as ambiguous and should be reviewed before finalizing the architecture.")
    result.report_markdown = build_report(result)
    return result


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    unique = []
    seen = set()
    for warning in warnings:
        key = " ".join(warning.casefold().split())
        if key not in seen:
            unique.append(warning)
            seen.add(key)
    return unique
