import uuid
from app.models import PipelineResult
from .parser import parse_requirements
from .components import extract_components
from .synthesizer import synthesize
from .tracer import build_trace
from .uml import use_case, class_diagram, sequence, activity
from .report import build_report
from .llm import is_enabled, run_llm_pipeline


def run_pipeline(text: str) -> PipelineResult:
    warnings = []
    ai_stages = []
    mode = "deterministic-fallback"

    if is_enabled():
        try:
            reqs, arch, trace, warnings, ai_stages = run_llm_pipeline(text)
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

    run_id = uuid.uuid4().hex[:10]
    uml = {
        "use_case": use_case(reqs),
        "class": class_diagram(arch),
        "sequence": sequence(arch),
        "activity": activity(),
    }
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
    )
    result.report_markdown = build_report(result)
    if any(r.type == "ambiguous" for r in reqs):
        result.warnings.append("One or more requirements were classified as ambiguous and should be reviewed before finalizing the architecture.")
    return result
