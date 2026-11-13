"""Local development server: `python api.py`, then open http://127.0.0.1:8000

Uses only the Python standard library, so FastAPI and uvicorn aren't needed
to try the app locally. It serves the same endpoints as the Vercel app
(api/index.py) and calls the same pipeline (mf_facts/service.py).

Put your LLM key in a `.env` file (see .env.example). It is git-ignored.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mf_facts import service
from mf_facts.live_nav import AMFI_NAV_URL, NavUnavailable, get_nav_client
from mf_facts.llm import LLMConfig
from mf_facts.schemes import SCHEMES

PROJECT_DIR = Path(__file__).resolve().parent
MAX_BODY_BYTES = 16_384


def load_dotenv(path: Path = PROJECT_DIR / ".env") -> None:
    """Minimal .env loader (KEY=value lines). Real env vars take precedence."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PROJECT_DIR), **kwargs)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/health":
            config = LLMConfig.from_env()
            return self._json(200, {
                "ok": True, "llm_configured": config is not None,
                "llm_provider": config.provider if config else None,
            })
        if url.path == "/api/schemes":
            return self._json(200, {"schemes": service.scheme_list()})
        if url.path == "/api/nav":
            scheme_id = (parse_qs(url.query).get("scheme") or [""])[0]
            if scheme_id not in SCHEMES:
                return self._json(404, {"detail": "Unknown scheme"})
            try:
                rows = get_nav_client().for_scheme(SCHEMES[scheme_id])
            except NavUnavailable:
                return self._json(503, {"detail": "AMFI NAV feed is unavailable right now"})
            return self._json(200, {
                "scheme": SCHEMES[scheme_id].name,
                "source": {"title": "AMFI", "url": AMFI_NAV_URL},
                "navs": [{"plan": label, "nav": r.nav, "date": r.date} for label, r in rows],
            })
        if url.path == "/":
            self.path = "/index.html"
            return super().do_GET()
        if url.path == "/index.html":
            return super().do_GET()
        # Only the web page is served as a file. Source code, .env and data
        # are not exposed by the local server.
        return self._json(404, {"detail": "Not found"})

    def do_POST(self):
        if urlparse(self.path).path != "/api/ask":
            return self._json(404, {"detail": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json(400, {"detail": "Invalid Content-Length"})
        if length < 1 or length > MAX_BODY_BYTES:
            return self._json(400, {"detail": f"Request body must be between 1 and {MAX_BODY_BYTES} bytes"})
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._json(400, {"detail": "Request body must be valid JSON"})
        if not isinstance(body, dict) or not isinstance(body.get("question"), str):
            return self._json(400, {"detail": "Provide a question string"})
        scheme = body.get("scheme")
        if scheme is not None and not isinstance(scheme, str):
            return self._json(400, {"detail": "scheme must be a string"})
        if len(body["question"]) > service.MAX_QUESTION_CHARS:
            return self._json(400, {"detail": f"Question must be {service.MAX_QUESTION_CHARS} characters or fewer"})
        try:
            result = service.answer_question(body["question"], scheme)
        except Exception as exc:
            print(f"[mf-facts] error: {type(exc).__name__}")
            return self._json(500, {"detail": "Unable to process the question right now"})
        if result is None:
            return self._json(400, {"detail": "Enter a question first"})
        return self._json(200, result)

    def _json(self, status, value):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        # Log method, path and status only, never request bodies (questions).
        pass


def main():
    load_dotenv()
    configured = LLMConfig.from_env()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Groww MF Facts: http://127.0.0.1:8000")
    print(f"LLM: {configured.provider} / {configured.model}" if configured
          else "LLM: not configured (set LLM_API_KEY in .env). Document answers will be unavailable.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
