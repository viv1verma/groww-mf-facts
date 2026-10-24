"""Vercel function adapter for the existing Groww MF Facts API."""
from http.server import BaseHTTPRequestHandler
import importlib.util
import json
from pathlib import Path
import sys


PROJECT_DIR = Path(__file__).resolve().parents[1]
_API_MODULE_NAME = "_groww_mf_facts_local_api"
_api_module = sys.modules.get(_API_MODULE_NAME)
if _api_module is None:
    _spec = importlib.util.spec_from_file_location(
        _API_MODULE_NAME, PROJECT_DIR / "api.py"
    )
    if _spec is None or _spec.loader is None:
        raise ImportError("Could not load the existing Groww MF Facts API")
    _api_module = importlib.util.module_from_spec(_spec)
    sys.modules[_API_MODULE_NAME] = _api_module
    _spec.loader.exec_module(_api_module)

answer_question = _api_module.answer_question


class handler(BaseHTTPRequestHandler):
    """Serve POST /api/ask using the existing answer and retrieval logic."""

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json(400, {"error": "Invalid Content-Length"})
        if length < 1 or length > 16_384:
            return self._json(
                400, {"error": "Request body must be between 1 and 16384 bytes"}
            )
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json(400, {"error": "Request body must be valid JSON"})
        if not isinstance(body, dict) or not isinstance(body.get("question"), str):
            return self._json(400, {"error": "Provide a question string"})

        question = body["question"]
        if len(question) > 2000:
            return self._json(400, {"error": "Question must be 2000 characters or fewer"})
        try:
            result = answer_question(question)
        except Exception:
            return self._json(500, {"error": "Unable to process the question right now"})
        if result is None:
            return self._json(400, {"error": "Enter a question first"})
        return self._json(200, result)

    def do_GET(self):
        return self._json(405, {"error": "Method not allowed"}, allow="POST")

    def _json(self, status, value, allow=None):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        if allow:
            self.send_header("Allow", allow)
        self.end_headers()
        self.wfile.write(payload)
