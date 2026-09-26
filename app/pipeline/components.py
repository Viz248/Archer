import re
from app.models import Component, Requirement

KEYWORDS = {
    "authentication": ("Authentication Service", "Handles identity, login, token/session validation.", ["JWT", "OAuth 2.0"]),
    "login": ("Authentication Service", "Handles identity, login, token/session validation.", ["JWT"]),
    "user": ("User Service", "Manages user profiles and account data.", ["REST"]),
    "profile": ("User Service", "Manages user profiles and account data.", ["REST"]),
    "payment": ("Payment Service", "Processes payments and coordinates with a payment provider.", ["Payment Gateway"]),
    "order": ("Order Service", "Creates and manages orders and their lifecycle.", ["REST", "PostgreSQL"]),
    "product": ("Catalog Service", "Provides product/catalog information and search.", ["REST", "PostgreSQL"]),
    "search": ("Search Service", "Indexes and searches domain data.", ["Search Index"]),
    "notification": ("Notification Service", "Sends email, SMS, or push notifications.", ["Message Queue"]),
    "email": ("Notification Service", "Sends transactional email notifications.", ["SMTP/Email API"]),
    "admin": ("Admin Service", "Provides privileged administration and monitoring functions.", ["REST"]),
    "report": ("Reporting Service", "Generates reports and analytics from persisted data.", ["SQL"]),
    "image": ("Image Processing Service", "Validates, preprocesses, and analyzes uploaded images.", ["Python", "OpenCV"]),
    "upload": ("File Storage Service", "Stores and retrieves uploaded documents or media.", ["Object Storage"]),
    "chat": ("Chat Service", "Manages conversational sessions and messages.", ["REST", "WebSocket"]),
    "ai": ("AI Inference Service", "Runs model inference and returns structured predictions.", ["Python", "ML Model"]),
    "model": ("AI Inference Service", "Runs model inference and returns structured predictions.", ["Python", "ML Model"]),
    "audit": ("Audit Service", "Records security and business events for traceability.", ["Append-only Log"]),
}

def extract_components(reqs: list[Requirement]) -> list[Component]:
    buckets = {}
    for r in reqs:
        low = r.text.lower()
        hits = [k for k in KEYWORDS if k in low]
        if not hits and r.type == "functional":
            # Noun-like fallback: first meaningful noun-ish phrase.
            name = re.sub(r"[^a-zA-Z ]", "", r.text).split()
            candidate = next((w for w in name if len(w) > 4), "Core")
            key = f"{candidate.title()} Service"
            buckets.setdefault(key, {"responsibility": f"Supports the capability described by: {r.text}", "reqs": [], "tech": ["REST"]})
            buckets[key]["reqs"].append(r.id)
        for k in hits:
            name, responsibility, tech = KEYWORDS[k]
            b = buckets.setdefault(name, {"responsibility": responsibility, "reqs": [], "tech": tech[:]})
            b["reqs"].append(r.id)
    components = []
    for i, (name, b) in enumerate(buckets.items(), 1):
        components.append(Component(id=f"COMP-{i:03d}", name=name, responsibility=b["responsibility"], requirements=sorted(set(b["reqs"])), technologies=sorted(set(b["tech"]))))
    if not components:
        components.append(Component(id="COMP-001", name="Application Service", responsibility="Coordinates the supplied requirements.", requirements=[r.id for r in reqs], technologies=["REST"]))
    return components
