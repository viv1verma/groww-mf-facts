
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from api import answer_question

app = FastAPI()


class QuestionRequest(BaseModel):
    question: str


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/ask")
def ask(request: QuestionRequest):
    result = answer_question(request.question)

    if result is None:
        raise HTTPException(status_code=400, detail="Enter a question first")

    return result
