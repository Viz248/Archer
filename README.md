# Archer — AI-Assisted Requirements-to-Architecture Synthesis System

Archer is an AI-assisted software engineering platform that synthesizes structured, explainable software architectures from natural-language requirements.

Rather than treating architecture generation as an opaque, single-prompt generation task, Archer implements an inspectable multi-stage pipeline. The system extracts candidate components, infers architectural styles and relationships, establishes bidirectional requirement traceability, evaluates architectural consistency through automated rules and reflection, and generates target-system UML/Mermaid diagrams and reports.

Archer provides dual execution modes:
1. **Live LLM Pipeline**: A model-backed chained workflow using structured outputs (via Groq, OpenAI, or Ollama) with prompt chaining, local tools, and semantic reflection.
2. **Deterministic Fallback**: A rule- and keyword-driven pipeline that runs without external API dependencies, ensuring reliability when API keys are absent or network requests fail.

---

## Key Features

- **Structured Requirement Parsing**: Normalizes unstructured requirement text into atomic `Requirement` records classified as `functional`, `non_functional`, or `ambiguous`, assigning stable identifiers (`REQ-001`, `REQ-002`, ...) and confidence scores.
- **Candidate Component Extraction**: Identifies cohesive architectural components, maps requirement IDs to each component, deduces component responsibilities, and suggests justified implementation technologies.
- **Architecture Synthesis**: Infers architectural styles (e.g., Layered, Event-Driven, Pipeline), defines directional component relationships with interaction kinds (`request`, `service-call`, `event`, `depends_on`, `audit-write`) and rationales, and categorizes design patterns as applied or recommended.
- **Bidirectional Traceability**: Links every requirement to architectural elements, explicit architectural decisions, rationales, and confidence levels.
- **Automated Architecture Evaluation**: Runs a deterministic evaluation engine that inspects architecture graphs and requirement coverage. It validates relationship endpoints (including recognized external actor boundaries), enforces dependency-cycle and pattern checks, downgrades requirement assessments when evidence, gaps, or availability constraints do not justify satisfaction, and generates actionable findings (`EvaluationFinding`) with unique IDs (`EV-<hash>`), severities, impact explanations, and recommended remediations.
- **Automated Diagram Generation**: Generates target-system Mermaid diagrams (Component/Architecture, Use-Case, Sequence, Activity/Workflow) with explicit availability status and fallback explanations, alongside internal pipeline workflow diagrams.
- **Comprehensive Markdown Reporting**: Compiles a detailed markdown architecture report containing requirements matrices, component catalogs, relationship graphs, traceability tables, evaluation findings, and diagram specifications.
- **Interactive Web Interface**: Single-page web console (`static/index.html`) featuring live mode indicators, tabbed inspection views, and dynamic client-side SVG rendering using Mermaid.js.

---

## How It Works

Archer executes a sequential pipeline where each stage produces validated data models consumed by subsequent stages:

```
Natural-Language Requirements
              │
              ▼
   [ 1. Requirement Parsing ]
              │  Atomic Requirements (REQ-xxx, type, confidence)
              ▼
   [ 2. Component Extraction ]
              │  Candidate Components & Requirement IDs
              ▼
  [ 3. Architecture Synthesis ]
              │  Style, Components, Relationships, Patterns
              ▼
  [ 4. Reflection / Traceability ]
              │  Trace Links & Requirement Satisfaction Assessments
              ▼
   [ 5. Architecture Evaluation ]
              │  Consistency Checks & Actionable Findings (EV-xxx)
              ▼
    [ 6. Diagram Generation ]
              │  Mermaid Diagrams (Architecture, Use-Case, Sequence, Activity)
              ▼
     [ 7. Report Generation ]
              │
              ▼
  PipelineResult Object & Web UI
```

### Execution Stages in Detail

1. **Requirement Parsing**:
   - *Live LLM*: Invokes structured output parsing with schema validation (`RequirementParseResult`), classifying each statement into `functional`, `non_functional`, or `ambiguous` with ambiguity explanations.
   - *Deterministic Fallback*: Splits sentences, applies regular expressions and heuristic keyword rules to categorize requirements and calculate confidence scores.
2. **Component Extraction**:
   - *Live LLM*: Solicits architectural components (`ComponentExtractionResult`), mapping requirement IDs to component responsibilities and technologies while verifying that requirement IDs exist.
   - *Deterministic Fallback*: Uses keyword-to-service mapping tables and noun extraction to populate candidate components and associate functional requirements.
3. **Architecture Synthesis**:
   - *Live LLM*: Prompts the model with candidate components and requirements, demanding strict candidate component preservation (`ArchitectureSynthesisResult`). Identifies applied patterns and filters recommended unapplied patterns.
   - *Deterministic Fallback*: Incurs external actors (`External: <Actor>`), constructs service dependency paths, establishes authentication dependencies (`depends_on`), routes event triggers (`event`), and assigns audit records (`audit-write`).
4. **Reflection and Traceability**:
   - *Live LLM*: Performs a reflection pass (`RationaleResult`) reviewing requirement coverage, creating trace links, and scoring requirement satisfaction (`satisfied`, `partially_satisfied`, `unresolved`) with evidence and gap notes.
   - *Deterministic Fallback*: Automatically generates deterministic trace links between requirements and their mapped architectural components.
5. **Architecture Evaluation**:
   - The deterministic evaluator (`app/pipeline/evaluator.py`) verifies the synthesized model against predefined architectural rules. It generates `EvaluationFinding` objects with deterministic identifiers (`EV-<hash>`), checking for:
     - Traceability errors (unknown requirements, invalid targets, untraced requirements).
     - Ambiguous requirements requiring clarification before architectural baselining.
     - Unrepresented architectural patterns declared without structural backing.
     - Relationship defects (nonexistent endpoints, dangling external boundaries, cyclic dependencies), validating endpoints against known components and recognized external actor prefixes (`external ` and `external:`).
     - High-availability claims lacking concrete redundancy mechanisms or measurable targets (e.g., uptime percentages or RTO/RPO targets).
     - Incomplete requirement satisfaction or unresolved gaps, downgrading requirement assessments when stated gaps, lack of supporting evidence, or unasserted availability mechanisms do not justify a satisfied status.
6. **Diagram Generation**:
   - The diagram generator (`app/pipeline/uml.py`) inspects architecture graphs and requirement cues to produce Mermaid source code:
     - **Architecture Diagram**: A top-down flowchart (`flowchart TD`) showing components, external actors, and typed dependency edges.
     - **Use-Case Diagram**: A horizontal flowchart (`flowchart LR`) showing actors or system triggers associated with requirement use cases.
     - **Sequence Diagram**: A sequence diagram (`sequenceDiagram`) generated when requirements contain explicit temporal cues (`when`, `after`, `then`) and traceable component paths.
     - **Activity Diagram**: A workflow flowchart (`flowchart TD`) generated for validated sequential scenarios.
     - **Domain Class Diagram**: Marked as `unavailable` with a documented architectural rationale (the pipeline operates on high-level services rather than entity attribute models).
     - **Internal Workflow Diagram**: An internal architectural diagram documenting Archer's own multi-stage pipeline.
7. **Report Generation**:
   - Compiles all metadata, tables, actionable findings, and diagram source blocks into a structured Markdown document (`app/pipeline/report.py`).

---

## Architecture and Technology Stack

### Backend
- **Python 3.11+ / 3.12+** (tested with Python 3.13)
- **FastAPI** (`0.116.1`): Web framework serving API endpoints and static assets.
- **Uvicorn** (`0.35.0`): ASGI web server.
- **Pydantic v2** (`2.11.7`): Data validation and structured output schemas.
- **Python-dotenv** (`1.1.1`): Environment variable management.

### Standalone Server
- **Zero-Dependency Mode**: `standalone_demo.py` uses the standard library `http.server.ThreadingHTTPServer` to serve the web interface and run deterministic synthesis without requiring third-party pip packages.

### Frontend
- **HTML5 / CSS3 / Vanilla JavaScript**: Responsive single-page interface (`static/index.html`) with no Node.js or npm build step required.
- **Mermaid.js v11** (loaded via CDN): Client-side SVG rendering for architecture, use-case, sequence, activity, and workflow diagrams.

### LLM Integration
- **OpenAI Python SDK** (`openai>=1.99.0,<3.0.0`): Uses the Responses API (`client.responses.parse`) with Pydantic structured output models.
- **Supported Providers**:
  - **Groq** (e.g., `openai/gpt-oss-20b`, `llama-3.3-70b-versatile`) with rate-limit backoff and parse error retries.
  - **OpenAI** (e.g., `gpt-5.6-terra`, `gpt-4o`).
  - **Azure OpenAI** via OpenAI-compatible endpoints.
  - **Ollama** (e.g., `qwen3:8b` via `http://localhost:11434/v1` chat completions in JSON mode).

### Data Models
- Core domain models are implemented as Python dataclasses in `app/models.py`:
  - `Requirement`: ID, text, type (`functional`, `non_functional`, `ambiguous`), confidence score.
  - `Component`: ID, name, responsibility, mapped requirement IDs, technologies.
  - `Relationship`: Source, target, kind, rationale.
  - `Architecture`: Style, components, relationships, applied patterns, recommended patterns.
  - `TraceLink`: Requirement ID, architectural element, decision, rationale, confidence.
  - `RequirementAssessment`: Requirement ID, satisfaction status, evidence, unresolved gaps, finding IDs.
  - `EvaluationFinding`: Finding ID, code, severity, subject, requirement IDs, message, impact, action.
  - `PipelineResult`: Run ID, execution mode, requirements, architecture, trace links, diagrams, report markdown, warnings, findings.

---

## Project Structure

```
Archer/
├── app/
│   ├── main.py                 # FastAPI application and route handlers
│   ├── models.py               # Domain dataclasses (Requirement, Component, etc.)
│   ├── pipeline/
│   │   ├── engine.py           # Pipeline orchestrator and fallback handling
│   │   ├── parser.py           # Deterministic requirement parser fallback
│   │   ├── components.py       # Deterministic component extractor fallback
│   │   ├── synthesizer.py      # Deterministic architecture synthesizer
│   │   ├── llm.py              # Model-backed stages, schemas, and LLM clients
│   │   ├── evaluator.py        # Architecture evaluation rules and findings
│   │   ├── tracer.py           # Deterministic traceability link generator
│   │   ├── uml.py              # Mermaid diagram generators (target and internal)
│   │   └── report.py           # Markdown report builder
│   └── services/               # Internal service utilities
├── static/
│   └── index.html              # Frontend user interface (HTML/CSS/JS)
├── tests/
│   ├── test_evaluator.py       # Unit tests for architecture evaluation checks
│   ├── test_pipeline.py        # Integration and LLM pipeline schema tests
│   ├── test_synthesizer.py     # Unit tests for deterministic synthesizer
│   └── test_uml.py             # Unit tests for Mermaid diagram generation
├── outputs/
│   └── sample_report.md        # Example generated markdown architecture report
├── .env.example                # Example environment configuration template
├── DEMO_SCRIPT.md              # Step-by-step walkthrough for live demonstrations
├── Dockerfile                  # Container build specification
├── docker-compose.yml          # Container composition definition
├── QUICKSTART.txt              # Quick reference setup notes
├── requirements.txt            # Python package dependencies
└── standalone_demo.py          # Zero-dependency Python HTTP server
```

---

## Prerequisites and Setup

### Prerequisites
- Python 3.11 or higher
- Git

### Option A: Standard Setup (Full FastAPI Application)

1. **Clone the repository and navigate to the directory**:
   ```bash
   git clone <repository-url>
   cd Archer
   ```

2. **Create and activate a virtual environment**:
   - **Linux / macOS**:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   - **Windows (PowerShell)**:
     ```powershell
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables** (optional for live LLM mode):
   ```bash
   cp .env.example .env
   ```
   Edit `.env` to supply your API key and provider settings (see [Configuration](#configuration)).

5. **Start the application**:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
   Access the web console at `http://127.0.0.1:8000`.

---

### Option B: Zero-Dependency Standalone Mode

To run Archer using only Python standard library modules without installing third-party pip packages:

```bash
python standalone_demo.py
```
Open `http://127.0.0.1:8000` in your browser. This mode executes the deterministic fallback pipeline.

---

### Option C: Docker Setup

To build and run the application in a Docker container:

```bash
docker compose up --build
```
Access the application at `http://127.0.0.1:8000`.

---

## Configuration

Archer configures model integration through environment variables or a local `.env` file. If configuration is missing or invalid, Archer automatically defaults to deterministic fallback mode.

### Environment Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `LLM_API_KEY` | String | *None* | Provider API key (e.g., Groq `gsk_...` or OpenAI `sk-...`). Required for live LLM execution. |
| `LLM_BASE_URL` | String | `https://api.openai.com/v1` | Base URL of the OpenAI-compatible endpoint (e.g., `https://api.groq.com/openai/v1` or `http://localhost:11434/v1`). |
| `LLM_MODEL` | String | `gpt-5.6-terra` | Model identifier to request (e.g., `openai/gpt-oss-20b`, `gpt-4o`, `qwen3:8b`). |
| `LLM_ENABLED` | Boolean | `true` | Explicit toggle (`true`, `false`, `1`, `0`). When disabled, runs deterministic fallback directly. |

### Configuration Examples

#### Groq Integration
```ini
LLM_ENABLED=true
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_your_groq_api_key_here
LLM_MODEL=openai/gpt-oss-20b
```

#### OpenAI Integration
```ini
LLM_ENABLED=true
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your_openai_api_key_here
LLM_MODEL=gpt-5.6-terra
```

#### Local Ollama Integration
```ini
LLM_ENABLED=true
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen3:8b
```

> [!CAUTION]
> Never commit `.env` or hard-code API keys in source files. The `.gitignore` file includes `.env` by default.

---

## Using Archer

### Web Interface

1. Open `http://127.0.0.1:8000`.
2. Inspect the header badge:
   - `● LIVE LLM · <model/provider>` indicates active model-backed synthesis.
   - `○ FALLBACK MODE · configure LLM_API_KEY` indicates deterministic fallback execution.
3. Provide input requirements:
   - Type or paste requirements into the **Requirements** text area (one statement per line).
   - Click **Load Sample** to populate standard e-commerce and notification requirements.
4. Click **Synthesize Architecture**.
5. Inspect the generated output across the tabbed panels:
   - **Overview**: Shows summary metrics (counts of requirements, components, trace links, relationships), run mode, architectural style, execution stages, and requirement satisfaction assessments.
   - **Architecture**: Displays synthesized components with responsibilities, mapped requirements, technologies, and typed directional relationships with rationales.
   - **Traceability**: Presents an interactive table detailing requirement mappings, architectural elements, decisions, rationales, and confidence scores.
   - **Evaluation**: Displays consistency findings (`EV-<hash>`), detailing affected requirements, finding descriptions, architectural impact, and recommended remediation steps.
   - **UML**: Renders SVG diagrams for the target system (Architecture, Use-Case, Sequence, Activity) with source-toggle buttons and copy utilities, alongside Archer's internal workflow diagram.
   - **Report**: Displays the full generated Markdown report with a **Download report.md** button.

### REST API Endpoints

- `GET /`: Serves the single-page frontend.
- `GET /health`: Returns service health status (`{"status": "ok"}`).
- `GET /api/sample`: Returns sample requirements text.
- `GET /api/config`: Returns runtime configuration (`llm_configured`, `model`, `provider`).
- `POST /api/analyze`: Synthesizes an architecture from requirements text.
  - **Request Body**:
    ```json
    {
      "requirements": "Users can register and log in.\nUsers can place orders and pay online.\nThe system shall send email notifications."
    }
    ```
  - **Response**: Serialized `PipelineResult` object containing requirements, architecture, trace links, diagrams, report markdown, findings, and warnings.

---

## Testing

Archer includes a comprehensive test suite covering architecture evaluation, deterministic synthesis, Mermaid diagram generation, and LLM structured output schema contracts.

### Running Tests

Execute the test suite using pytest:

```bash
python -m pytest
```

### Verified Test Suite Status

The latest verified test run passed **90 tests**:
- `tests/test_evaluator.py`: 31 passed (evaluates availability checks, recognized external actor endpoints, dangling relationship detection, cyclic dependency checks, trace validation).
- `tests/test_pipeline.py`: 36 passed (verifies pipeline execution, live-LLM availability assessment downgrades, structured output schemas, provider rate-limit handling, LLM synthesis constraints).
- `tests/test_synthesizer.py`: 5 passed (tests deterministic synthesis, event trigger parsing, audit relationships, external actor extraction).
- `tests/test_uml.py`: 18 passed (tests Mermaid syntax escaping, label wrapping, actor association, sequence flow derivation).

---

## Limitations and Future Work

### Current Limitations
- **High-Level Service Granularity**: Architecture synthesis operates on coarse-grained components and microservices. Detailed domain class diagrams with attribute and method signatures are marked as unavailable because natural-language system requirements do not specify low-level object models.
- **Workflow Sequence Constraints**: System sequence and activity diagrams require explicit sequential or causal cues (e.g., `when`, `after`, `then`) in the requirements to infer interaction order; absent such cues, workflow diagrams are safely marked unavailable.
- **Strict Component Preservation Contract**: In live LLM synthesis, candidate components extracted during Stage 2 must be preserved 1:1 in Stage 3 without additions, renamings, or omissions. Non-compliant model outputs trigger fallback to preserve contract integrity.
- **Heuristic Deterministic Parsing**: When running in fallback mode, component extraction relies on keyword lookups and noun-matching heuristics rather than deep semantic comprehension.

### Planned Improvements
- **Domain Entity Synthesis**: Adding an entity extraction stage to infer domain aggregates and generate class diagrams.
- **Interactive Refinement**: Enabling architects to edit components, add relationship constraints, and re-evaluate findings directly in the UI.
- **Conversational Clarification**: Integrating a multi-turn dialogue loop to resolve requirements flagged as `ambiguous`.
- **Extended Diagram Export**: Supporting export to PlantUML, Structurizr DSL, and C4-PlantUML formats.

---

## Research and Evaluation

Archer is developed as a prototype exploring multi-stage LLM pipelines for software architecture synthesis. It incorporates design patterns discussed in software engineering literature, including prompt chaining, tool use, structured output validation, routing, reflection, and evaluator-optimizer loops.

The research goals outlined for this architecture synthesis approach focus on:
1. **Requirements-to-Decision Traceability**: Ensuring every architectural component and relationship links to concrete requirements.
2. **Consistency & Constraint Verification**: Catching architectural flaws (unsupported availability claims, cyclic dependencies, missing components) prior to implementation.
3. **Reproducibility**: Structuring model boundaries to reduce nondeterministic hallucination.

For demonstration scenarios and live evaluation scripts, see [DEMO_SCRIPT.md](DEMO_SCRIPT.md). For an example of generated synthesis output, see [outputs/sample_report.md](outputs/sample_report.md).

> [!NOTE]
> Published experimental metrics (such as measured architectural accuracy percentages, design-time savings, or multi-run consistency statistics) have not yet been formally established. Archer is designed to generate traceable artifacts to support empirical evaluation in future studies.

---

## License and Acknowledgements

### License
A software license has not yet been specified for this repository.

### Acknowledgements
Archer utilizes several open-source libraries:
- [FastAPI](https://fastapi.tiangolo.com/) and [Starlette](https://www.starlette.io/)
- [Pydantic](https://docs.pydantic.dev/)
- [Uvicorn](https://www.uvicorn.org/)
- [Mermaid.js](https://mermaid.js.org/)
- [OpenAI Python SDK](https://github.com/openai/openai-python)
- [pytest](https://docs.pytest.org/)
