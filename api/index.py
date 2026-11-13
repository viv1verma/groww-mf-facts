"""Vercel entry point: FastAPI app serving the frontend and the JSON API.

Endpoints
    GET  /                 the web app (index.html)
    GET  /api/health       status, including whether an LLM key is configured
    GET  /api/schemes      the schemes this prototype covers
    GET  /api/nav?scheme=  latest AMFI NAV for one scheme
    POST /api/ask          {"question": "...", "scheme": "<optional scheme id>"}
"""
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from mf_facts import service  # noqa: E402
from mf_facts.live_nav import NavUnavailable, get_nav_client  # noqa: E402
from mf_facts.llm import LLMConfig  # noqa: E402
from mf_facts.schemes import SCHEMES  # noqa: E402

app = FastAPI(title="Groww MF Facts", docs_url=None, redoc_url=None)


class QuestionRequest(BaseModel):
    question: str = Field(max_length=service.MAX_QUESTION_CHARS)
    scheme: str | None = Field(default=None, max_length=80)


@app.get("/")
def home():
    return FileResponse(PROJECT_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    config = LLMConfig.from_env()
    # Report whether the document index loads, so a deployment that is
    # missing data/index/chunks.json (or a library) is easy to spot. Only the
    # error type is shown, never details.
    try:
        from mf_facts.index_store import get_index
        index_status = {"index_chunks": len(get_index().chunks)}
    except Exception as exc:
        index_status = {"index_error": type(exc).__name__}
    return {
        "ok": True,
        "llm_configured": config is not None,
        "llm_provider": config.provider if config else None,
        **index_status,
    }


@app.get("/api/schemes")
def schemes():
    return {"schemes": service.scheme_list()}


@app.get("/api/nav")
def nav(scheme: str = Query(..., max_length=80)):
    if scheme not in SCHEMES:
        raise HTTPException(status_code=404, detail="Unknown scheme")
    try:
        rows = get_nav_client().for_scheme(SCHEMES[scheme])
    except NavUnavailable:
        raise HTTPException(status_code=503, detail="AMFI NAV feed is unavailable right now")
    return {
        "scheme": SCHEMES[scheme].name,
        "source": {"title": "AMFI", "url": "https://portal.amfiindia.com/spages/NAVAll.txt"},
        "navs": [{"plan": label, "nav": r.nav, "date": r.date} for label, r in rows],
    }


@app.post("/api/ask")
def ask(request: QuestionRequest):
    try:
        result = service.answer_question(request.question, request.scheme)
    except Exception as exc:  # Never leak internals to the browser.
        print(f"[mf-facts] error: {type(exc).__name__}")
        raise HTTPException(status_code=500, detail="Unable to process the question right now")
    if result is None:
        raise HTTPException(status_code=400, detail="Enter a question first")
    return result
