"""Tests for safety rules, scheme resolution, grounding checks and the pipeline.

None of these call a real LLM or the network. FakeLLM stands in for the
model so the tests can cover both well-behaved and badly-behaved replies.
Run: python -m unittest
"""
import re
import unittest
from pathlib import Path

from mf_facts import grounding, service
from mf_facts.index_store import get_index
from mf_facts.live_nav import AmfiNavClient
from mf_facts.llm import LLMError, parse_json_object
from mf_facts.safety import contains_personal_data, is_advice_request
from mf_facts.schemes import SCHEMES, resolve_schemes

NIFTY = "hdfc-nifty-50-index-fund"
FLEXI = "hdfc-flexi-cap-fund"
MID = "hdfc-mid-cap-fund"
ELSS = "hdfc-elss-tax-saver-fund"
FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "amfi_nav_sample.txt"


class FakeLLM:
    """Returns a scripted reply and records what it was sent."""

    def __init__(self, reply=None, fn=None, error=None):
        self.reply, self.fn, self.error = reply, fn, error
        self.calls = []

    def complete_json(self, system, user, max_tokens=500):
        self.calls.append(user)
        if self.error:
            raise self.error
        return self.fn(user) if self.fn else self.reply


def passage_ids(prompt):
    return re.findall(r"^\[(P\d+)\] Scheme: ([^|]+?) \|", prompt, re.M)


def quoting_llm(pattern, template):
    """A well-behaved fake: finds a passage matching `pattern` and answers from it."""
    def fn(prompt):
        blocks = re.split(r"\n\n---\n\n", prompt.split("Passages:\n\n", 1)[1])
        for block in blocks:
            m = re.search(pattern, block, re.I | re.S)
            if m:
                pid = re.match(r"\[(P\d+)\]", block).group(1)
                scheme = re.match(r"\[P\d+\] Scheme: ([^|]+?) \|", block).group(1)
                return {"status": "answered", "answer": template.format(scheme=scheme, m=m), "citations": [pid]}
        return {"status": "not_found", "answer": "", "citations": []}
    return fn


class SafetyTests(unittest.TestCase):
    def test_advice_requests_are_detected(self):
        for q in [
            "Should I buy this fund?", "Is HDFC Nifty 50 good for me?", "Should I put money in mid cap?",
            "Which fund is better, flexi cap or mid cap?", "Will it give 12% returns?",
            "Is it worth investing now?", "How much should I invest monthly?",
            "Can you suggest a fund for my retirement?", "Is flexi cap a good investment?",
            "Will this fund double in 5 years?", "Is it suitable for me?",
            "What will the NIFTY 50 close at tomorrow?", "What will the NAV be next week?",
        ]:
            with self.subTest(q=q):
                self.assertTrue(is_advice_request(q))

    def test_factual_questions_are_not_refused(self):
        for q in [
            "What is the exit load if I redeem now?", "Can you explain exit load for me?",
            "Who is the fund manager?", "Which index does it track?",
            "What were the returns of HDFC Mid Cap Fund last year?", "What is the lock-in period for ELSS?",
            "Compare the expense ratio of flexi cap and mid cap", "Will the exit load apply after 5 days?",
            "What will the exit load be if I redeem in 2 days?",
        ]:
            with self.subTest(q=q):
                self.assertFalse(is_advice_request(q))

    def test_personal_data_is_detected(self):
        for q in ["My PAN is ABCDE1234F", "call me on 9876543210", "aadhaar 1234 5678 9012",
                  "mail me@example.com", "my OTP is 482913", "folio 12345678"]:
            with self.subTest(q=q):
                self.assertTrue(contains_personal_data(q))
        self.assertFalse(contains_personal_data("Exit load is 0.25% within 3 days; AUM ₹22,245.78 Cr"))


class SchemeResolutionTests(unittest.TestCase):
    def ids(self, q, selected=None):
        r = resolve_schemes(q, selected)
        return [s.id for s in r.schemes], r.unsupported

    def test_short_names_resolve_to_the_right_scheme(self):
        # These two questions used to return HDFC Nifty 50 Index Fund facts.
        self.assertEqual(self.ids("What's the expense ratio of the ELSS fund?"), ([ELSS], False))
        self.assertEqual(self.ids("exit load for mid cap fund"), ([MID], False))
        self.assertEqual(self.ids("flexicap benchmark"), ([FLEXI], False))
        self.assertEqual(self.ids("tax saver lock in"), ([ELSS], False))

    def test_question_overrides_ui_selection(self):
        self.assertEqual(self.ids("exit load of mid cap", selected=NIFTY), ([MID], False))

    def test_ui_selection_used_when_question_names_nothing(self):
        self.assertEqual(self.ids("What is the exit load?", selected=FLEXI), ([FLEXI], False))
        self.assertEqual(self.ids("What is the exit load?"), ([], False))

    def test_uncovered_schemes_are_unsupported(self):
        for q in ["min SIP for HDFC Nifty 100 Index Fund", "exit load of nifty midcap 150 index fund",
                  "exit load of SBI Bluechip", "nifty 50 equal weight fund TER", "HDFC small cap fund exit load"]:
            with self.subTest(q=q):
                self.assertEqual(self.ids(q, selected=NIFTY), ([], True))

    def test_benchmark_index_name_is_context_not_another_scheme(self):
        self.assertEqual(self.ids("Is the mid cap fund benchmarked to Nifty Midcap 150?"), ([MID], False))
        self.assertEqual(self.ids("HDFC mid cap vs HDFC Nifty Midcap 150 Index Fund"), ([], True))

    def test_covered_scheme_with_other_company_name_is_answered(self):
        self.assertEqual(self.ids("Does HDFC Flexi Cap hold ICICI Bank?"), ([FLEXI], False))

    def test_multiple_schemes(self):
        self.assertEqual(self.ids("Compare expense ratio of flexi cap and mid cap"), ([FLEXI, MID], False))


class GroundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index = get_index()
        cls.scheme = SCHEMES[NIFTY]
        chunk = next(c for c in index.chunks if c.scheme_id == NIFTY and "0.25%" in c.text and "3 days" in c.text)
        other = next(c for c in index.chunks if c.scheme_id == MID)
        cls.passages = [grounding.Passage("P1", chunk), grounding.Passage("P2", other)]

    def verify(self, reply, schemes=None):
        return grounding.verify(reply, self.passages, schemes or [self.scheme])

    def test_supported_answer_passes(self):
        v = self.verify({"status": "answered", "citations": ["P1"],
                         "answer": "For HDFC Nifty 50 Index Fund, an exit load of 0.25% applies if units are redeemed within 3 days of allotment."})
        self.assertTrue(v.ok, v.reason)

    def test_number_not_in_sources_is_rejected(self):
        v = self.verify({"status": "answered", "citations": ["P1"],
                         "answer": "For HDFC Nifty 50 Index Fund, an exit load of 1% applies within 365 days."})
        self.assertEqual(v.reason, "unsupported_number")

    def test_invented_citation_is_rejected(self):
        v = self.verify({"status": "answered", "citations": ["P9"], "answer": "HDFC Nifty 50 Index Fund exit load is 0.25%."})
        self.assertEqual(v.reason, "unknown_citation")

    def test_citing_another_scheme_is_rejected(self):
        v = self.verify({"status": "answered", "citations": ["P2"], "answer": "HDFC Nifty 50 Index Fund exit load is 0.25%."})
        self.assertEqual(v.reason, "wrong_scheme")

    def test_answer_must_name_the_scheme(self):
        v = self.verify({"status": "answered", "citations": ["P1"], "answer": "The exit load is 0.25% within 3 days."})
        self.assertEqual(v.reason, "scheme_not_named")

    def test_urls_and_advice_are_rejected(self):
        self.assertEqual(self.verify({"status": "answered", "citations": ["P1"],
                                      "answer": "HDFC Nifty 50 Index Fund: see https://example.com"}).reason, "url_in_answer")
        self.assertEqual(self.verify({"status": "answered", "citations": ["P1"],
                                      "answer": "HDFC Nifty 50 Index Fund is a good investment; you should invest."}).reason, "advice_in_answer")

    def test_not_found_and_malformed_replies_abstain(self):
        self.assertFalse(self.verify({"status": "not_found"}).ok)
        self.assertFalse(self.verify({"status": "answered", "answer": "", "citations": ["P1"]}).ok)
        self.assertFalse(self.verify({"status": "answered", "answer": "HDFC Nifty 50 Index Fund", "citations": []}).ok)

    def test_json_parsing_tolerates_fences(self):
        self.assertEqual(parse_json_object('```json\n{"status": "not_found"}\n```'), {"status": "not_found"})
        with self.assertRaises(LLMError):
            parse_json_object("no json here")


class ServiceTests(unittest.TestCase):
    def ask(self, q, scheme=None, llm=None, nav=None):
        return service.answer_question(q, scheme, llm=llm, nav_client=nav)

    def test_empty_question(self):
        self.assertIsNone(self.ask("   "))

    def test_advice_and_pii_never_reach_the_llm(self):
        llm = FakeLLM(reply={})
        self.assertEqual(self.ask("Should I buy HDFC Mid Cap Fund?", llm=llm)["kind"], "refusal")
        self.assertEqual(self.ask("My PAN is ABCDE1234F, what is the exit load?", NIFTY, llm=llm)["kind"], "pii")
        self.assertEqual(llm.calls, [])

    def test_no_scheme_asks_to_clarify(self):
        r = self.ask("What is the exit load?", llm=FakeLLM(reply={}))
        self.assertEqual(r["kind"], "clarify")
        self.assertEqual(len(r["scheme_options"]), 4)

    def test_unsupported_scheme_abstains_without_citation(self):
        r = self.ask("What is the minimum SIP for HDFC Nifty 100 Index Fund?", NIFTY, llm=FakeLLM(reply={}))
        self.assertEqual(r["kind"], "unsupported")
        self.assertEqual(r["citations"], [])
        self.assertIsNone(r["source_url"])

    def test_llm_only_sees_passages_for_the_resolved_scheme(self):
        # Regression: "the ELSS fund" previously got Nifty 50 figures.
        llm = FakeLLM(reply={"status": "not_found"})
        self.ask("What's the expense ratio of the ELSS fund?", NIFTY, llm=llm)
        schemes_seen = {name for _, name in passage_ids(llm.calls[0])}
        self.assertEqual(schemes_seen, {"HDFC ELSS Tax Saver Fund"})

    def test_comparison_retrieves_each_scheme(self):
        llm = FakeLLM(reply={"status": "not_found"})
        self.ask("Compare the exit load of flexi cap and mid cap", llm=llm)
        schemes_seen = {name for _, name in passage_ids(llm.calls[0])}
        self.assertEqual(schemes_seen, {"HDFC Flexi Cap Fund", "HDFC Mid Cap Fund"})

    def test_grounded_answer_has_code_built_citation(self):
        llm = FakeLLM(fn=quoting_llm(r"exit load of (0\.25%).{0,80}?within (3 days)",
                                     "For {scheme}, an exit load of {m[1]} applies if units are redeemed within {m[2]} of allotment."))
        r = self.ask("What is the exit load?", NIFTY, llm=llm)
        self.assertEqual(r["kind"], "answer", r.get("abstain_reason"))
        self.assertIn("0.25%", r["answer"])
        self.assertEqual(r["schemes"], ["HDFC Nifty 50 Index Fund"])
        c = r["citations"][0]
        self.assertTrue(c["url"].startswith("https://files.hdfcfund.com/"))
        self.assertIn("#page=", c["url"])
        self.assertIn("0.25%", c["quote"])
        self.assertGreater(c["page_number"], 0)

    def test_minimum_sip_answered_from_documents(self):
        # Formerly a hard-coded string; now must be found in the PDFs.
        llm = FakeLLM(fn=quoting_llm(r"Rs\.? ?(100)/?-? and any amount thereafter",
                                     "For {scheme}, the minimum purchase amount is Rs. {m[1]} and any amount thereafter."))
        r = self.ask("What is the minimum SIP amount?", NIFTY, llm=llm)
        self.assertEqual(r["kind"], "answer", r.get("abstain_reason"))

    def test_hallucinated_figure_becomes_abstention(self):
        llm = FakeLLM(fn=lambda prompt: {"status": "answered", "citations": ["P1"],
                                         "answer": "HDFC Mid Cap Fund has an expense ratio of 0.07%."})
        r = self.ask("What is the expense ratio of HDFC Mid Cap Fund?", llm=llm)
        self.assertEqual(r["kind"], "abstain")
        self.assertEqual(r["abstain_reason"], "unsupported_number")
        self.assertEqual(r["citations"], [])
        self.assertTrue(r["related_documents"])

    def test_llm_failure_is_reported_as_unavailable(self):
        r = self.ask("What is the exit load?", MID, llm=FakeLLM(error=LLMError("LLM HTTP 429")))
        self.assertEqual(r["kind"], "unavailable")
        self.assertEqual(r["citations"], [])

    def test_missing_llm_config_is_reported(self):
        r = self.ask("What is the exit load?", MID, llm=None)
        self.assertEqual(r["kind"], "unavailable")

    def test_nav_question_uses_amfi_without_llm(self):
        nav = AmfiNavClient(fetch=lambda: FIXTURE.read_text(encoding="utf-8"))
        llm = FakeLLM(reply={})
        r = self.ask("What is the latest NAV of HDFC Mid Cap Fund?", llm=llm, nav=nav)
        self.assertEqual(r["kind"], "nav")
        self.assertIn("₹207.802", r["answer"])
        self.assertIn("₹230.663", r["answer"])
        self.assertIn("12-Nov-2026", r["answer"])
        self.assertEqual(r["citations"][0]["publisher"], "AMFI")
        self.assertEqual(llm.calls, [])


class LiveNavTests(unittest.TestCase):
    def test_parses_amfi_file_and_skips_unavailable_values(self):
        from mf_facts.live_nav import parse_nav_file
        records = parse_nav_file(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(records[101525].nav, "241.8155")
        self.assertEqual(records[101525].plan, "Regular Plan")
        self.assertNotIn(999999, records)

    def test_every_scheme_has_both_growth_plans_in_amfi(self):
        nav = AmfiNavClient(fetch=lambda: FIXTURE.read_text(encoding="utf-8"))
        for s in SCHEMES.values():
            with self.subTest(scheme=s.name):
                rows = nav.for_scheme(s)
                self.assertEqual(len(rows), 2)
                for _, rec in rows:
                    self.assertIn(s.name.replace("ELSS Tax Saver", "ELSS - Tax Saver"), rec.scheme_name)
                    self.assertEqual(rec.option, "Growth Option")


if __name__ == "__main__":
    unittest.main()


class LLMFallbackTests(unittest.TestCase):
    def test_busy_model_falls_back_to_next(self):
        from mf_facts import llm as llm_mod
        config = llm_mod.LLMConfig("gemini", "https://x", "main", "k", fallbacks=("backup",))
        client = llm_mod.ChatClient(config)
        tried = []

        def fake(model, system, user, max_tokens):
            tried.append(model)
            if model == "main":
                raise llm_mod._Retryable("HTTP 503")
            return {"status": "not_found"}

        client._complete = fake
        self.assertEqual(client.complete_json("s", "u"), {"status": "not_found"})
        self.assertEqual(tried, ["main", "backup"])

    def test_all_models_busy_raises_llm_error(self):
        from mf_facts import llm as llm_mod
        client = llm_mod.ChatClient(llm_mod.LLMConfig("gemini", "https://x", "main", "k", fallbacks=("b",)))

        def busy(*a):
            raise llm_mod._Retryable("HTTP 503")

        client._complete = busy
        with self.assertRaises(LLMError):
            client.complete_json("s", "u")


class NumberParsingTests(unittest.TestCase):
    def test_dates_without_space_and_indian_grouping(self):
        from mf_facts.grounding import _numbers
        self.assertEqual(_numbers("since August 26,2026"), _numbers("since August 26, 2026"))
        self.assertEqual(_numbers("₹22,245.78 Cr"), {"22245.780000"})
        self.assertEqual(_numbers("1,00,000"), {"100000.000000"})


class FollowUpTests(unittest.TestCase):
    def test_llm_suggestions_are_filtered_and_topped_up(self):
        from mf_facts.followups import build_follow_ups
        mid = [SCHEMES[MID]]
        out = build_follow_ups("What is the exit load?", mid, [
            "Should I invest in this fund now?",            # advice → dropped
            "What is the exit load of HDFC Nifty 100 Index Fund?",  # not covered → dropped
            "What is the benchmark of HDFC Flexi Cap Fund?",  # another scheme → dropped
            "What is the exit load?",                        # repeats the question → dropped
            "Who manages the fund",                          # kept, gets "?"
        ])
        questions = [f["question"] for f in out]
        self.assertEqual(questions[0], "Who manages the fund?")
        self.assertEqual(len(out), 3)
        self.assertTrue(all(f["scheme"] == MID for f in out))
        self.assertFalse(any("exit load" in q.lower() for q in questions))
        self.assertFalse(any("lock-in" in q.lower() for q in questions))  # not ELSS

    def test_elss_catalog_offers_lock_in(self):
        from mf_facts.followups import build_follow_ups
        out = build_follow_ups("What is the exit load?", [SCHEMES[ELSS]])
        self.assertIn("What is the lock-in period?", [f["question"] for f in out])

    def test_multi_scheme_follow_ups_name_the_schemes(self):
        from mf_facts.followups import build_follow_ups
        out = build_follow_ups("Compare the exit load of flexi cap and mid cap", [SCHEMES[FLEXI], SCHEMES[MID]],
                               ["What is the benchmark?"])  # names no scheme → dropped
        self.assertTrue(out)
        for f in out:
            r = resolve_schemes(f["question"])
            self.assertEqual({s.id for s in r.schemes}, {FLEXI, MID})

    def test_answer_includes_follow_ups(self):
        def fn(prompt):
            reply = quoting_llm(r"exit load of (0\.25%).{0,80}?within (3 days)",
                                "For {scheme}, an exit load of {m[1]} applies within {m[2]} of allotment.")(prompt)
            reply["follow_ups"] = ["What is the benchmark index?", "Is it a good time to buy?"]
            return reply
        r = service.answer_question("What is the exit load?", NIFTY, llm=FakeLLM(fn=fn))
        self.assertEqual(r["kind"], "answer")
        self.assertEqual(r["follow_ups"][0], {"question": "What is the benchmark index?", "scheme": NIFTY})
        self.assertNotIn("Is it a good time to buy?", [f["question"] for f in r["follow_ups"]])

    def test_refusal_and_unsupported(self):
        r = service.answer_question("Should I buy this fund?", MID, llm=FakeLLM(reply={}))
        self.assertTrue(r["follow_ups"])  # factual alternatives for the scheme in view
        r = service.answer_question("Exit load of SBI Bluechip?", MID, llm=FakeLLM(reply={}))
        self.assertEqual(r["follow_ups"], [])


class LLMConfigTests(unittest.TestCase):
    def test_key_whitespace_from_dashboard_is_trimmed(self):
        from unittest import mock
        from mf_facts.llm import LLMConfig
        with mock.patch.dict("os.environ", {"LLM_PROVIDER": " gemini\n", "LLM_API_KEY": "AIzaTEST \n"}, clear=True):
            config = LLMConfig.from_env()
        self.assertEqual(config.api_key, "AIzaTEST")
        self.assertEqual(config.provider, "gemini")

    def test_bad_header_becomes_llm_error_not_crash(self):
        from mf_facts.llm import ChatClient, LLMConfig
        client = ChatClient(LLMConfig("gemini", "https://example.invalid", "m", "bad\nkey"))
        with self.assertRaises(LLMError):
            client.complete_json("s", "u")
