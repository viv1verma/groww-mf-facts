"""Local HTTP API and static frontend server for Groww MF Facts."""
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse

from retrieval import answer_question as retrieve_answer, load_pdf_chunks

PROJECT_DIR = Path(__file__).resolve().parent
ADVICE_TERMS = [
    "should i buy", "should i sell", "buy or sell", "should i invest",
    "is this a good investment", "best mutual fund", "recommend a fund",
    "which fund should", "my portfolio", "portfolio allocation",
    "where should i invest", "will it give returns", "predict returns",
    "target return", "which mutual fund is best", "suggest a fund",
]
ADVICE_RESPONSE = (
    "I can provide factual information from official scheme documents, but I can’t "
    "recommend whether you should buy, hold, or sell or suggest a portfolio. "
    "Please consult a SEBI-registered investment adviser for personalised advice."
)
UNVERIFIED_RESPONSE = (
    "I’m sorry, but I couldn’t find a reliable answer to that in the official "
    "documents I currently have available. I don’t want to give you incorrect "
    "information. You could try another question about the fund, or check HDFC "
    "Mutual Fund’s official scheme documents for the latest details."
)


@lru_cache(maxsize=1)
def get_chunks():
    return load_pdf_chunks()


def answer_question(question: str, chunks=None):
    question = question.strip()
    if not question:
        return None
    if any(term in question.lower() for term in ADVICE_TERMS):
        return {
            "answer": ADVICE_RESPONSE, "source_url": None,
            "source_title": None, "document_date": None,
            "page_number": None, "refusal": True,
        }
    result = retrieve_answer(question, chunks=get_chunks() if chunks is None else chunks)
    if not result:
        return {
            "answer": UNVERIFIED_RESPONSE, "source_url": None,
            "source_title": None, "document_date": None, "page_number": None,
            "refusal": False, "unverified": True,
        }
    return {
        "answer": result["answer"], "source_url": result["source_url"],
        "source_title": result["source_title"],
        "document_date": result["document_date"],
        "page_number": result.get("page_number"), "refusal": False,
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._json(200, {"ok": True})
        if path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/ask":
            return self._json(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json(400, {"error": "Invalid Content-Length"})
        if length < 1 or length > 16_384:
            return self._json(400, {"error": "Request body must be between 1 and 16384 bytes"})
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json(400, {"error": "Request body must be valid JSON"})
        if not isinstance(body, dict) or not isinstance(body.get("question"), str):
            return self._json(400, {"error": "Provide a question string"})
        question = body["question"]
        if len(question) > 2000:
            return self._json(400, {"error": "Question must be 2000 characters or fewer"})
        result = answer_question(question)
        if result is None:
            return self._json(400, {"error": "Enter a question first"})
        return self._json(200, result)

    def _json(self, status, value):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Groww MF Facts frontend and API: http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
