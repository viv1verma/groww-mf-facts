"""The question-to-answer pipeline, shared by the local server and Vercel.

    question
      │
      ├─ 1. validate (non-empty, ≤ 2000 chars)
      ├─ 2. personal data?      → stop, warn, never sent to the LLM
      ├─ 3. advice request?     → polite refusal
      ├─ 4. resolve scheme(s)   → unsupported → abstain / none → ask which scheme
      ├─ 5. NAV question?       → live AMFI NAV (exact published figures)
      ├─ 6. retrieve passages   → top passages for each scheme only
      ├─ 7. LLM writes answer   → JSON {status, answer, citations}
      ├─ 8. verify in code      → citations real, numbers in sources, no advice
      └─ 9. answer + citations built from document metadata, or abstain

Every response has a `kind` so the UI can show the right state.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from . import grounding
from .index_store import DOC_TYPE_LABEL, SOURCES_PATH, Index, get_index
from .followups import build_follow_ups
from .live_nav import AMFI_NAV_URL, AMFI_SOURCE_TITLE, NavUnavailable, get_nav_client
from .llm import ChatClient, LLMError, get_client
from .safety import ADVICE_RESPONSE, PII_RESPONSE, contains_personal_data, is_advice_request
from .schemes import SCHEMES, Scheme, resolve_schemes

MAX_QUESTION_CHARS = 2000

_NAV_RE = re.compile(
    r"\bnav\b|net asset value|\b(?:current|latest|today'?s?)\s+(?:price|value|unit price)\b|"
    r"\bunit price\b|\bprice (?:today|now)\b",
    re.IGNORECASE,
)

_UNSET = object()


def _base(kind: str, answer: str, **extra) -> dict:
    out = {
        "kind": kind,
        "answer": answer,
        "citations": [],
        "schemes": [],
        # Older single-source fields, kept so existing clients keep working.
        "source_url": None,
        "source_title": None,
        "document_date": None,
        "page_number": None,
        # Suggested next questions: [{"question": str, "scheme": id or None}]
        "follow_ups": [],
        "refusal": kind in ("refusal", "pii"),
        "unverified": kind in ("abstain", "unsupported", "unavailable", "clarify"),
    }
    out.update(extra)
    return out


def scheme_list() -> list[dict]:
    return [{"id": s.id, "name": s.name, "category": s.category} for s in SCHEMES.values()]


@lru_cache(maxsize=1)
def _sources() -> dict:
    return {r["file_name"]: r for r in json.loads(SOURCES_PATH.read_text(encoding="utf-8"))}


def official_documents(scheme: Scheme) -> list[dict]:
    """Official document links for a scheme, taken from sources.json."""
    docs = []
    for d in scheme.documents:
        meta = _sources().get(d.file_name)
        if meta and meta.get("source_url"):
            docs.append({
                "title": meta.get("source_title", d.file_name),
                "url": meta["source_url"],
                "document_type": DOC_TYPE_LABEL[d.doc_type],
                "date": meta.get("document_date", ""),
            })
    return docs


def _abstain(schemes: list[Scheme], reason: str, question: str = "") -> dict:
    names = " and ".join(s.name for s in schemes)
    return _base(
        "abstain",
        f"I couldn't find a reliable answer to that in the official documents I have for {names}. "
        "I'd rather not guess with financial information. You can check the official "
        "documents below, or try rephrasing the question.",
        schemes=[s.name for s in schemes],
        related_documents=[d for s in schemes for d in official_documents(s)],
        abstain_reason=reason,
        # Offer questions this scheme's documents are known to answer.
        follow_ups=build_follow_ups(question, schemes),
    )


def _nav_answer(schemes: list[Scheme], nav_client) -> dict:
    lines, records = [], []
    try:
        for s in schemes:
            parts = []
            for label, rec in nav_client.for_scheme(s):
                parts.append(f"{label} ₹{rec.nav}")
                records.append(rec)
            lines.append(f"{s.name}: " + "; ".join(parts) + f" (NAV date {records[-1].date}).")
    except NavUnavailable:
        return _base(
            "unavailable",
            "I couldn't reach AMFI's live NAV feed just now. Please try again shortly.",
            schemes=[s.name for s in schemes],
        )
    date = records[0].date if records else ""
    answer = "Latest NAV published by AMFI. " + " ".join(lines) + (
        " NAV is updated once each business day. It is not a real-time price."
    )
    citation = {
        "title": AMFI_SOURCE_TITLE, "publisher": "AMFI", "url": AMFI_NAV_URL,
        "document_url": AMFI_NAV_URL, "document_type": "Daily NAV file", "scheme": None,
        "date": f"NAV date {date}", "page_number": None, "page_link": False,
        "quote": "; ".join(f"{r.scheme_name} – {r.plan} – {r.option}: {r.nav} ({r.date})" for r in records),
    }
    return _base(
        "nav", answer, schemes=[s.name for s in schemes], citations=[citation],
        source_url=AMFI_NAV_URL, source_title=AMFI_SOURCE_TITLE, document_date=f"NAV date {date}",
        follow_ups=build_follow_ups("What is the latest NAV?", schemes),
    )


def answer_question(
    question: str,
    scheme_id: str | None = None,
    *,
    index: Index | None = None,
    llm: ChatClient | None | object = _UNSET,
    nav_client=None,
) -> dict | None:
    """Answer one question. Returns None only for an empty question."""
    question = (question or "").strip()
    if not question:
        return None
    if len(question) > MAX_QUESTION_CHARS:
        return _base("error", f"Please keep questions under {MAX_QUESTION_CHARS} characters.")

    if contains_personal_data(question):
        return _base("pii", PII_RESPONSE)
    if is_advice_request(question):
        # Point to factual questions about the scheme in view, if any.
        in_view = resolve_schemes(question, scheme_id)
        return _base(
            "refusal", ADVICE_RESPONSE,
            follow_ups=[] if in_view.unsupported else build_follow_ups(question, in_view.schemes),
        )

    resolution = resolve_schemes(question, scheme_id)
    if resolution.unsupported:
        names = ", ".join(s.name for s in SCHEMES.values())
        return _base(
            "unsupported",
            f"I can only answer about these schemes right now: {names}. Your question seems to be "
            "about a different scheme or fund house, so I won't guess.",
            scheme_options=scheme_list(),
        )
    schemes = resolution.schemes
    if not schemes:
        return _base(
            "clarify",
            "Which scheme is your question about? Please pick one so I answer from the right documents.",
            scheme_options=scheme_list(),
        )

    if _NAV_RE.search(question):
        return _nav_answer(schemes, nav_client or get_nav_client())

    client = get_client() if llm is _UNSET else llm
    if client is None:
        return _base(
            "unavailable",
            "The AI answer service isn't configured on this server yet, so I can't answer "
            "document questions right now. Live NAV questions still work.",
            schemes=[s.name for s in schemes],
            related_documents=[d for s in schemes for d in official_documents(s)],
        )

    index = index or get_index()
    # (key-facts passages, other passages) per scheme. Fewer each when
    # several schemes are compared, to keep the prompt small.
    key_k, other_k = {1: (4, 5), 2: (3, 3)}.get(len(schemes), (2, 2))
    passages: list[grounding.Passage] = []
    for s in schemes[:4]:
        for chunk, _score in index.search_balanced(question, s, key_k, other_k):
            passages.append(grounding.Passage(f"P{len(passages) + 1}", chunk))
    if not passages:
        return _abstain(schemes, "no_passages", question)

    try:
        reply = client.complete_json(
            grounding.SYSTEM_PROMPT, grounding.build_user_prompt(question, schemes, passages)
        )
    except LLMError as exc:
        print(f"[mf-facts] llm_error: {exc}")
        return _base(
            "unavailable",
            "The answer service is busy or unavailable right now (the free AI tier may be "
            "rate-limited). Please try again in a minute.",
            schemes=[s.name for s in schemes],
        )

    verdict = grounding.verify(reply, passages, schemes)
    if not verdict.ok:
        # Log only the reason code, never the question, to protect privacy.
        print(f"[mf-facts] abstain: {verdict.reason}")
        return _abstain(schemes, verdict.reason, question)

    citations = [grounding.citation_for(c, verdict.answer) for c in verdict.cited]
    first = verdict.cited[0]
    return _base(
        "answer", verdict.answer,
        schemes=[s.name for s in schemes],
        citations=citations,
        source_url=citations[0]["url"], source_title=first.source_title,
        document_date=first.document_date, page_number=first.page_number,
        follow_ups=build_follow_ups(question, schemes, reply.get("follow_ups")),
    )
