import json
import importlib.util
import threading
import unittest
from http.server import ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api import Handler, answer_question


class BundlerScriptParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.payloads = []
        self.current_type = None
        self.current_text = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        kind = values.get("type", "")
        if tag == "script" and kind.startswith("__bundler/"):
            self.current_type = kind
            self.current_text = []

    def handle_data(self, data):
        if self.current_type:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current_type:
            self.payloads.append((self.current_type, "".join(self.current_text)))
            self.current_type = None


class ApiBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:{}".format(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_frontend_and_health_are_served(self):
        with urlopen(self.base + "/") as response:
            self.assertEqual(response.status, 200)
            html = response.read().decode("utf-8")
            self.assertIn("__bundler/template", html)
        with urlopen(self.base + "/api/health") as response:
            self.assertEqual(json.load(response), {"ok": True})

    def test_browser_receives_valid_json_for_each_bundle_payload(self):
        with urlopen(self.base + "/") as response:
            parser = BundlerScriptParser()
            parser.feed(response.read().decode("utf-8"))
        self.assertTrue(parser.payloads)
        for name, payload in parser.payloads:
            with self.subTest(payload=name):
                json.loads(payload)

    def test_ask_returns_answer_and_citation_metadata(self):
        request = Request(
            self.base + "/api/ask",
            data=json.dumps({"question": "What is the benchmark?"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request) as response:
            result = json.load(response)
        self.assertIn("NIFTY 50", result["answer"])
        self.assertTrue(result["source_url"].startswith("https://"))
        self.assertTrue(result["document_date"])
        self.assertIsNone(result["page_number"])

    def test_personalized_advice_refusal_has_no_citation_card_data(self):
        result = answer_question("Should I buy this fund?", chunks=[])
        self.assertTrue(result["refusal"])
        self.assertIn("can’t recommend", result["answer"])
        self.assertIsNone(result["source_url"])
        self.assertIsNone(result["source_title"])
        self.assertIsNone(result["document_date"])
        self.assertIsNone(result["page_number"])

    def test_unsupported_question_uses_polite_fallback_without_citation(self):
        result = answer_question("What is this fund's office address?", chunks=[])
        self.assertEqual(
            result["answer"],
            "I’m sorry, but I couldn’t find a reliable answer to that in the official "
            "documents I currently have available. I don’t want to give you incorrect "
            "information. You could try another question about the fund, or check HDFC "
            "Mutual Fund’s official scheme documents for the latest details.",
        )
        self.assertTrue(result["unverified"])
        self.assertFalse(result["refusal"])
        self.assertIsNone(result["source_url"])


    def test_nifty_100_minimum_sip_abstention_has_no_nifty_50_citation(self):
        result = answer_question(
            "What is the minimum SIP amount for HDFC Nifty 100 Index Fund?",
            chunks=[],
        )
        self.assertTrue(result["unverified"])
        self.assertIsNone(result["source_url"])
        self.assertIsNone(result["source_title"])
        self.assertNotIn("₹100", result["answer"])

    def test_other_scheme_minimum_sip_abstentions_have_no_nifty_50_citation(self):
        schemes = (
            "HDFC Flexi Cap Fund",
            "HDFC Mid Cap Fund",
            "HDFC ELSS Tax Saver Fund",
        )
        for scheme in schemes:
            with self.subTest(scheme=scheme):
                result = answer_question(
                    "What is the minimum SIP amount for {}?".format(scheme),
                    chunks=[],
                )
                self.assertTrue(result["unverified"])
                self.assertIsNone(result["source_url"])
                self.assertIsNone(result["source_title"])
                self.assertNotIn("₹100", result["answer"])

    def test_invalid_payload_returns_bad_request(self):
        request = Request(
            self.base + "/api/ask", data=b'{"question": 12}',
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(json.load(caught.exception), {"error": "Provide a question string"})


class VercelFunctionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent / "api" / "ask.py"
        spec = importlib.util.spec_from_file_location("test_vercel_ask", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), module.handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:{}".format(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_vercel_ask_route_preserves_grounded_answer_and_citation(self):
        request = Request(
            self.base + "/api/ask",
            data=json.dumps({"question": "What is the benchmark?"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            result = json.load(response)
        self.assertIn("NIFTY 50", result["answer"])
        self.assertTrue(result["source_url"].startswith("https://"))
        self.assertEqual(result["source_title"], "HDFC Nifty 50 Index Fund scheme page")
        self.assertIsNone(result["page_number"])


if __name__ == "__main__":
    unittest.main()
