"""HTTP tests for both entry points: the local server (api.py) and Vercel (api/index.py)."""
import importlib.util
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api import Handler
from mf_facts import service

PROJECT_DIR = Path(__file__).resolve().parent


def post(base, body):
    req = Request(base + "/api/ask", data=json.dumps(body).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req) as res:
        return json.load(res)


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_frontend_health_and_schemes(self):
        with urlopen(self.base + "/") as res:
            html = res.read().decode()
        self.assertIn("<title>Groww MF Facts</title>", html)
        self.assertNotIn("AMFI and SEBI documents", html)  # old, inaccurate claim
        with urlopen(self.base + "/api/health") as res:
            self.assertTrue(json.load(res)["ok"])
        with urlopen(self.base + "/api/schemes") as res:
            self.assertEqual(len(json.load(res)["schemes"]), 4)

    def test_project_files_are_not_served(self):
        for path in ("/.env", "/sources.json", "/api.py", "/mf_facts/service.py"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                urlopen(self.base + path)
            self.assertEqual(caught.exception.code, 404)

    def test_refusal_over_http(self):
        r = post(self.base, {"question": "Should I buy this fund?"})
        self.assertEqual(r["kind"], "refusal")
        self.assertTrue(r["refusal"])
        self.assertIsNone(r["source_url"])

    def test_invalid_payloads(self):
        for body, msg in ((b'{"question": 12}', "Provide a question string"),
                          (b"not json", "Request body must be valid JSON")):
            req = Request(self.base + "/api/ask", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with self.subTest(body=body), self.assertRaises(HTTPError) as caught:
                urlopen(req)
            self.assertEqual(caught.exception.code, 400)
            self.assertEqual(json.load(caught.exception)["detail"], msg)


class VercelAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        spec = importlib.util.spec_from_file_location("vercel_index", PROJECT_DIR / "api" / "index.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.client = TestClient(module.app)

    def test_routes(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertTrue(self.client.get("/api/health").json()["ok"])
        self.assertEqual(len(self.client.get("/api/schemes").json()["schemes"]), 4)
        self.assertEqual(self.client.get("/api/nav?scheme=unknown").status_code, 404)

    def test_question_length_is_limited(self):
        r = self.client.post("/api/ask", json={"question": "x" * (service.MAX_QUESTION_CHARS + 1)})
        self.assertEqual(r.status_code, 422)

    def test_ask_passes_scheme_through(self):
        with mock.patch.object(service, "answer_question", return_value={"kind": "answer", "answer": "ok"}) as m:
            r = self.client.post("/api/ask", json={"question": "What is the exit load?", "scheme": "hdfc-mid-cap-fund"})
        self.assertEqual(r.json()["answer"], "ok")
        m.assert_called_once_with("What is the exit load?", "hdfc-mid-cap-fund")

    def test_internal_errors_are_not_leaked(self):
        with mock.patch.object(service, "answer_question", side_effect=RuntimeError("secret detail")):
            r = self.client.post("/api/ask", json={"question": "hi"})
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("secret", r.text)


if __name__ == "__main__":
    unittest.main()
