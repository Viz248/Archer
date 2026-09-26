# Req2Arch — AI Assisted Requirements to Architecture Synthesis Demo

This version is a **real model-backed prototype** of the supplied IEEE project. It keeps the deterministic pipeline as a safety fallback, but when `LLM_API_KEY` is configured it runs a chained LLM workflow with structured outputs:

**Requirements → LLM Parser → LLM Component Extractor → LLM Architecture Synthesizer → Reflection/Evaluator → Traceability → UML → Report**

The implementation mirrors the paper's emphasis on prompt chaining, tool use, structured output, routing, reflection, evaluator-optimizer, and requirement-to-decision traceability.

## 1. Install

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

## 2. Configure the LLM

Copy `.env.example` to `.env` or set environment variables directly:

```text
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-5.6-terra
```

The application reads the key from the environment. **Do not commit `.env` or your API key.**

The OpenAI Python SDK supports the Responses API and Pydantic structured parsing used by this project. The model can be changed through `LLM_MODEL` if your account uses a different supported model.

## 3. Run

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## What makes this version different

Each run sends the requirements through several model-backed stages. Therefore changing the requirements changes the extracted components, architecture style, relationships, patterns, rationale, and warnings. Re-running the same requirements can also produce variation because the model is not replaced by a fixed keyword template.

The UI shows whether the run used `live-llm` or `deterministic-fallback`.

## Demo tips

Try two very different requirement sets:

### E-commerce
- Users can register and sign in.
- Users can search a product catalog.
- Users can create orders and pay online.
- The system sends order notifications.

### Retinal screening
- Clinicians upload retinal images.
- The system preprocesses images and predicts diabetic retinopathy severity.
- The result must include confidence and an explanation.
- Patient data must be auditable and access controlled.
- The inference service should work without a continuous internet connection.

The resulting architectures should differ materially.

## Evaluation

The supplied paper explicitly states that measured experimental results are not yet available. This demo does not invent accuracy or productivity numbers. It gives you a real artifact-generation pipeline that can be used to collect those measurements later.
