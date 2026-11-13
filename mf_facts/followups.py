"""Suggested follow-up questions shown under an answer.

Two sources, combined:
1. The LLM proposes up to 3 next questions from the same passages it used
   for the answer, so they are likely to be answerable.
2. A fixed catalog of questions verified by the evaluation set fills any gaps.

Every LLM suggestion is checked before it is shown. A suggestion is dropped
if it asks for advice or contains personal data, names a scheme we don't
cover, drifts to a different scheme, or repeats the question just asked.
Each follow-up carries the scheme id it belongs to, so clicking it asks about
the same scheme even if the user changes the selection.
"""
from __future__ import annotations

import re

from .safety import contains_personal_data, is_advice_request
from .schemes import Scheme, resolve_schemes

MAX_FOLLOW_UPS = 3
ELSS_ID = "hdfc-elss-tax-saver-fund"

# (topic pattern, question). The pattern detects whether a question is
# already about this topic, so we don't suggest what was just asked.
CATALOG = [
    (r"exit load|redeem|redemption", "What is the exit load?"),
    (r"expense|\bter\b|cost|charges?", "What is the expense ratio?"),
    (r"manag", "Who is the fund manager?"),
    (r"benchmark|track", "What is the benchmark?"),
    (r"lock", "What is the lock-in period?"),  # ELSS only, see below
    (r"\bnav\b|net asset value", "What is the latest NAV?"),
    (r"launch|inception|start", "When was it launched?"),
    (r"objective|aim|invest in", "What is the investment objective?"),
]


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _topic(text: str) -> str | None:
    q = text.lower()
    for pattern, question in CATALOG:
        if re.search(pattern, q):
            return question
    return None


def _clean(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    q = re.sub(r"\s+", " ", raw).strip().strip('"').strip()
    if not 8 <= len(q) <= 110 or re.search(r"https?://|www\.", q, re.I):
        return None
    return q if q.endswith("?") else q + "?"


def _catalog_for(schemes: list[Scheme], asked: str) -> list[dict]:
    if len(schemes) > 2:
        return []
    asked_topic = _topic(asked)
    catalog = list(CATALOG)
    if any(s.id == ELSS_ID for s in schemes):
        # The lock-in is the defining fact of an ELSS fund, so it goes first.
        catalog.sort(key=lambda item: item[1] != "What is the lock-in period?")
    out = []
    for _pattern, question in catalog:
        if question == asked_topic:
            continue
        if question == "What is the lock-in period?" and not any(s.id == ELSS_ID for s in schemes):
            continue
        if len(schemes) == 1:
            out.append({"question": question, "scheme": schemes[0].id})
        elif question != "What is the latest NAV?":
            # "What is the exit load?" → "Compare the exit load of A and B"
            subject = re.sub(r"^(?:What|Who) is (?:the )?|\?$", "", question)
            out.append({
                "question": f"Compare the {subject} of {schemes[0].name} and {schemes[1].name}?",
                "scheme": None,
            })
    return out


def build_follow_ups(asked: str, schemes: list[Scheme], llm_suggestions=None) -> list[dict]:
    """Return up to MAX_FOLLOW_UPS checked follow-ups: [{question, scheme}]."""
    if not schemes:
        return []
    allowed = {s.id for s in schemes}
    seen = {_norm(asked)}
    seen_topics = {_topic(asked)} - {None}
    out: list[dict] = []

    def add(item: dict) -> None:
        key = _norm(item["question"])
        topic = _topic(item["question"])
        if key in seen or (topic and topic in seen_topics) or len(out) >= MAX_FOLLOW_UPS:
            return
        seen.add(key)
        if topic:
            seen_topics.add(topic)
        out.append(item)

    for raw in (llm_suggestions or [])[:5]:
        q = _clean(raw)
        if not q or is_advice_request(q) or contains_personal_data(q):
            continue
        resolution = resolve_schemes(q)
        if resolution.unsupported:
            continue
        named = {s.id for s in resolution.schemes}
        if named and not named <= allowed:
            continue  # drifted to a different scheme
        if len(schemes) == 1:
            add({"question": q, "scheme": schemes[0].id})
        elif named:
            # For multi-scheme answers, the follow-up must name its scheme(s).
            add({"question": q, "scheme": next(iter(named)) if len(named) == 1 else None})

    for item in _catalog_for(schemes, asked):
        add(item)
    return out
