"""Run the evaluation set against the real pipeline (real LLM, live AMFI).

    python eval/run_eval.py            # uses LLM_* settings from .env / environment
    python eval/run_eval.py --verbose  # also print every answer

It reports, per question, whether the response kind matched and whether the
answer contained the required facts and none of the forbidden ones (e.g. a
Nifty 50 figure in a Mid Cap answer). The summary metrics are the ones a
facts-only product should track over time:

    accuracy        answered correctly when an answer was expected
    wrong-answer    answered with a forbidden or missing fact  (target: 0)
    abstain/refuse  behaved safely when it should not answer
"""
import json
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from api import load_dotenv  # noqa: E402
from mf_facts import service  # noqa: E402
from mf_facts.llm import LLMConfig  # noqa: E402

SAFE_KINDS = {"abstain", "unsupported", "refusal", "clarify", "pii"}


def grade(case, result):
    kind = result["kind"]
    expect = case["expect"]
    text = result["answer"].lower()
    missing = [s for s in case.get("must_contain", []) if s.lower() not in text]
    forbidden = [s for s in case.get("must_not_contain", []) if s.lower() in text]

    if kind in ("unavailable", "error"):
        return "MISS", f"service {kind}"
    if forbidden:
        return "WRONG", f"contains forbidden {forbidden}"
    if expect == "answer":
        if kind != "answer":
            return "MISS", f"expected answer, got {kind} ({result.get('abstain_reason', '')})"
        if missing:
            return "WRONG", f"missing {missing}"
        return "PASS", ""
    if expect == "answer_or_abstain":
        return ("PASS", "") if kind in ("answer", "abstain") else ("MISS", f"got {kind}")
    if expect == "refusal_or_abstain":
        return ("PASS", "") if kind in ("refusal", "abstain") else ("WRONG", f"got {kind}")
    if kind == expect:
        return "PASS", ""
    if kind == "answer":
        return "WRONG", f"answered but expected {expect}"
    return "MISS", f"expected {expect}, got {kind}"


def main():
    load_dotenv()
    verbose = "--verbose" in sys.argv
    config = LLMConfig.from_env()
    print(f"LLM: {config.provider} / {config.model}" if config else "LLM: not configured (document answers will be 'unavailable')")
    cases = json.loads((PROJECT_DIR / "eval" / "questions.json").read_text(encoding="utf-8"))
    counts = {"PASS": 0, "MISS": 0, "WRONG": 0}
    for i, case in enumerate(cases, 1):
        result = service.answer_question(case["q"], case.get("scheme"))
        status, note = grade(case, result)
        counts[status] += 1
        print(f"{status:5} {i:2d}. [{result['kind']}] {case['q']}" + (f"  — {note}" if note else ""))
        if verbose and result["kind"] in ("answer", "nav"):
            print(f"         {result['answer']}")
        if config:
            time.sleep(2.5)  # stay under free-tier requests-per-minute limits
    total = len(cases)
    print(f"\n{counts['PASS']}/{total} passed · {counts['MISS']} missed (safe) · {counts['WRONG']} wrong (unsafe, target 0)")
    return 1 if counts["WRONG"] else 0


if __name__ == "__main__":
    sys.exit(main())
