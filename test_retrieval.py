import unittest

from retrieval import answer_question, load_catalog_source, load_pdf_chunks, load_sources


class RetrievalAnswerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.chunks = load_pdf_chunks()

    def test_benchmark_has_official_source(self):
        answer = answer_question("What is the benchmark for HDFC Nifty 50 Index Fund?", self.chunks)
        self.assertIsNotNone(answer)
        self.assertIn("NIFTY 50", answer["answer"])
        self.assertIn("hdfcfund.com", answer["source_url"])
        self.assertIsNone(answer["page_number"])

    def test_expense_ratio_names_plan_figures_and_pdf_page(self):
        answer = answer_question("What is the expense ratio?", self.chunks)
        self.assertIsNotNone(answer)
        self.assertIn("0.41%", answer["answer"])
        self.assertIn("0.26%", answer["answer"])
        self.assertEqual(answer["page_number"], 9)
        self.assertIn("September 2026", answer["document_date"])

    def test_minimum_sip_uses_scheme_page_evidence(self):
        answer = answer_question("What is the minimum SIP amount?", self.chunks)
        source = load_catalog_source("HDFC Nifty 50 Index Fund scheme page")
        self.assertIsNotNone(answer)
        self.assertIn("₹100", answer["answer"])
        self.assertIn("Min SIP ₹100", answer["evidence"])
        self.assertEqual(answer["source_url"], source["url"])
        self.assertEqual(answer["source_title"], source["title"])
        self.assertEqual(answer["document_date"], source["document_or_check_date"])
        self.assertIsNone(answer["page_number"])

    def test_minimum_sip_nifty_100_abstains_without_nifty_50_citation(self):
        answer = answer_question(
            "What is the minimum SIP amount for HDFC Nifty 100 Index Fund?",
            self.chunks,
        )
        self.assertIsNone(answer)

    def test_unsupported_scheme_minimum_sip_questions_abstain(self):
        questions = [
            "What is the minimum SIP amount for HDFC Flexi Cap Fund?",
            "What is the minimum SIP amount for HDFC Mid Cap Fund?",
            "What is the minimum SIP amount for HDFC ELSS Tax Saver Fund?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertIsNone(answer_question(question, self.chunks))

    def test_other_hardcoded_nifty_50_facts_do_not_cross_schemes(self):
        questions = [
            "What is the benchmark for HDFC Nifty 100 Index Fund?",
            "What is the expense ratio for HDFC Nifty 100 Index Fund?",
            "What is the exit load for HDFC Nifty 100 Index Fund?",
            "What is the riskometer for HDFC Nifty 100 Index Fund?",
        ]
        for question in questions:
            with self.subTest(question=question):
                self.assertIsNone(answer_question(question, self.chunks))

    def test_pdf_citations_match_metadata_and_supporting_pages(self):
        sources = load_sources()
        for question in (
            "What is the expense ratio?",
            "What is the exit load of HDFC Nifty 50 Index Fund?",
        ):
            with self.subTest(question=question):
                answer = answer_question(question, self.chunks)
                source = sources["HDFC MF Index Factsheet - September 2026.pdf"]
                self.assertEqual(answer["source_url"], source["source_url"])
                self.assertEqual(answer["source_title"], source["source_title"])
                self.assertEqual(answer["document_date"], source["document_date"])
                self.assertGreater(answer["page_number"], 0)
                if "expense" in question:
                    self.assertEqual(answer["page_number"], 9)
                    self.assertIn("0.41%", answer["evidence"])
                    self.assertIn("0.26%", answer["evidence"])
                else:
                    self.assertEqual(answer["page_number"], 9)
                    self.assertIn("0.25", answer["evidence"])
                    self.assertIn("3 days", answer["evidence"])

    def test_exit_load_is_supported_by_loaded_pdf(self):
        answer = answer_question("What is the exit load of HDFC Nifty 50 Index Fund?", self.chunks)
        self.assertIsNotNone(answer)
        self.assertIn("0.25%", answer["answer"])
        self.assertIn("within 3 days", answer["answer"])
        self.assertGreater(answer["page_number"], 0)
        self.assertTrue(answer["source_url"].endswith(".pdf?VersionId=ifZn2abNfFlERun_stwnoMdkld729b5o"))

    def test_unsupported_question_abstains(self):
        self.assertIsNone(answer_question("What is the CEO's favorite color?", self.chunks))


if __name__ == "__main__":
    unittest.main()
