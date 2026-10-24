
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path

from api import answer_question

app = FastAPI()
PROJECT_DIR = Path(__file__).resolve().parent.parent


class QuestionRequest(BaseModel):
    question: str


@app.get("/")
def home():
    return FileResponse(PROJECT_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/ask")
def ask(request: QuestionRequest):
    result = answer_question(request.question)

    if result is None:
        raise HTTPException(status_code=400, detail="Enter a question first")

    return result
