import re
from app.models import Requirement

NON_FUNCTIONAL = [
    "scalab", "availability", "reliab", "latency", "performance", "secure", "security",
    "encrypt", "audit", "compliance", "uptime", "response time", "throughput", "backup",
    "fault tolerant", "maintainable", "extensible", "reproduc", "privacy"
]

def parse_requirements(text: str) -> list[Requirement]:
    lines = [x.strip(" -•\t") for x in text.splitlines() if x.strip()]
    if len(lines) == 1:
        # Split common prose requirement sentences without destroying short inputs.
        lines = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", lines[0]) if s.strip()]
    reqs = []
    for i, line in enumerate(lines, 1):
        low = line.lower()
        rtype = "non_functional" if any(k in low for k in NON_FUNCTIONAL) else "functional"
        ambiguous = len(line.split()) < 4 or any(k in low for k in ["etc", "something", "appropriate", "fast", "easy"])
        if ambiguous:
            rtype = "ambiguous"
        confidence = 0.92 if rtype == "functional" else 0.86 if rtype == "non_functional" else 0.62
        reqs.append(Requirement(id=f"REQ-{i:03d}", text=line, type=rtype, confidence=confidence))
    return reqs
