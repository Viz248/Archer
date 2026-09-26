from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from .pipeline.engine import run_pipeline
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="AI Assisted Requirements to Architecture Synthesis", version="1.0.0")

class AnalyzeRequest(BaseModel):
    requirements: str

@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse("static/index.html")

@app.get("/api/config")
def config():
    from .pipeline.llm import is_enabled, _model, _provider
    return {"llm_configured": is_enabled(), "model": _model(), "provider": _provider()}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/api/analyze")
def analyze(body: AnalyzeRequest):
    if not body.requirements.strip():
        raise HTTPException(400, "Requirements cannot be empty")
    return run_pipeline(body.requirements).to_dict()

@app.get("/api/sample")
def sample():
    return {"requirements": """Users shall be able to register and log in securely.\nUsers shall browse products and search the catalog.\nUsers shall create orders and pay online.\nThe system shall send an email notification when an order is placed.\nThe system shall support high availability and audit important actions."""}
