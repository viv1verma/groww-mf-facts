"""Retrieval tests: the right passages reach the LLM for each scheme.

If one of these fails after you replace a document, look at the passages
returned for that question and adjust QUERY_EXPANSIONS or the chunking in
mf_facts/index_store.py.
"""
import re
import unittest

from mf_facts.index_store import get_index, load_chunks
from mf_facts.schemes import SCHEMES

# question → a pattern the supporting passage must contain
CORE_QUESTIONS = {
    "What is the exit load?": r"exit load",
    "What is the expense ratio?": r"\d\.\d+ ?%",
    "What is the minimum SIP amount?": r"(?:Rs\.?|₹|INR) ?\d+",
    "What is the benchmark?": r"\bTRI\b",
    "What is the investment objective?": r"investment objective",
}


class IndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = get_index()

    def test_every_chunk_has_official_source_metadata(self):
        for c in load_chunks():
            self.assertTrue(c.source_url.startswith("https://"), c.id)
            self.assertGreater(c.page_number, 0)
            self.assertIn(c.scheme_id, SCHEMES)

    def test_multi_scheme_factsheet_only_contributes_its_scheme_pages(self):
        pages = {c.page_number for c in self.index.chunks if c.doc_type == "factsheet"}
        self.assertEqual(pages, {9, 10})

    def test_search_never_returns_another_schemes_passage(self):
        for scheme in SCHEMES.values():
            for q in CORE_QUESTIONS:
                with self.subTest(scheme=scheme.name, q=q):
                    results = self.index.search(q, scheme, k=6)
                    self.assertTrue(results)
                    self.assertTrue(all(c.scheme_id == scheme.id for c, _ in results))

    def test_supporting_passage_is_in_top_six(self):
        for scheme in SCHEMES.values():
            for q, pattern in CORE_QUESTIONS.items():
                with self.subTest(scheme=scheme.name, q=q):
                    texts = [c.text for c, _ in self.index.search(q, scheme, k=6)]
                    self.assertTrue(any(re.search(pattern, t) for t in texts))

    def test_elss_lock_in_passage_is_retrieved(self):
        texts = [c.text for c, _ in self.index.search("What is the lock-in period?", SCHEMES["hdfc-elss-tax-saver-fund"])]
        self.assertTrue(any(re.search(r"lock.?in", t, re.I) for t in texts))


if __name__ == "__main__":
    unittest.main()
