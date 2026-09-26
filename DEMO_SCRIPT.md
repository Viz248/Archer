# Req2Arch — 4–6 Minute Live Demo Script

## Before the demo

1. Set `LLM_API_KEY` in `.env`.
2. Optionally set `LLM_MODEL` (default: `gpt-5.6-terra`).
3. Start with:

```bash
uvicorn app.main:app --reload
```

4. Open `http://127.0.0.1:8000` and confirm the badge says **LIVE LLM**.

## Demo input A — e-commerce

Paste:

```text
Users can register and sign in.
Users can search and filter a product catalog.
Users can create orders and pay online.
The system sends order notifications.
The platform should remain available during traffic spikes.
Important business actions must be auditable.
```

Click **Synthesize Architecture**.

### What to show

1. **Overview** — point out the run ID and `live-llm` mode.
2. **Architecture** — show that the components and relationships were generated from the actual requirements.
3. **Traceability** — pick one requirement and show its architectural decision and rationale.
4. **UML** — show that the diagrams are generated from the generated architecture rather than being fixed screenshots.
5. **Report** — show the generated report and AI stages.

### Suggested explanation

> “This is not a fixed keyword-to-template demo. The requirements go through multiple model-backed stages. The model first classifies the requirements, then extracts components, then synthesizes the architecture, and finally performs a reflection/evaluator pass to create trace links and warnings. Structured outputs keep every stage machine-readable.”

## Demo input B — change the domain

Replace the requirements with:

```text
Clinicians upload retinal images.
The system preprocesses images and predicts diabetic retinopathy severity.
The result must include confidence and an explanation.
Patient data must be access controlled and auditable.
The inference workflow should continue to work without a continuous internet connection.
```

Run it again.

### What to show

Point out that the generated architecture is now different: image processing, inference/model-serving, explanation, audit/access control, and offline-oriented concerns should appear instead of the e-commerce services.

## Key project claims you can safely make

- The system uses a **multi-stage architecture-generation pipeline** rather than one opaque generation call.
- The implementation uses **structured model outputs** at pipeline boundaries.
- Requirement IDs are preserved so architectural decisions can be traced back to requirements.
- A separate **reflection/evaluator stage** reviews coverage and records warnings.
- UML and the report are generated from the synthesized architecture object.
- The application has a deterministic fallback if the LLM is not configured or an API request fails.

## Do not claim

Do not claim a measured architecture accuracy percentage, productivity improvement, or consistency percentage yet. The supplied project paper explicitly says those measurements have not been provided. Those can be collected as the next evaluation phase.
