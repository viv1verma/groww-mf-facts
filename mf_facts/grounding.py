"""Grounded answer generation: the prompt sent to the LLM and the checks on its reply.

The LLM is treated as an untrusted writer. It may only use the numbered
passages we give it, and its reply is checked in code before it is shown:

1. It must return valid JSON with status "answered" or "not_found".
2. Every passage it cites must be one we actually supplied.
3. Every number in the answer (0.25%, ₹100, 3 days, 22,245.78…) must appear in
   the cited passages. This catches the most damaging kind of hallucination
   in a finance product: a wrong figure.
4. The answer must contain no URLs and no advice phrasing.
5. The answer must name each scheme it covers.

If any check fails, we abstain. Citations (title, URL, page, date, quote) are
always built in code from the chunk metadata, never written by the LLM, so a
source link can't be invented.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .index_store import DOC_TYPE_LABEL, Chunk
from .safety import answer_contains_advice
from .schemes import Scheme

SYSTEM_PROMPT = """You are Groww MF Facts, a facts-only assistant for Indian mutual fund scheme documents.

Answer the user's question using ONLY the numbered passages provided. They are extracts from official HDFC Mutual Fund documents.

Rules:
- Use only facts stated in the passages. Do not use outside knowledge, do not estimate, and do not calculate new figures.
- Copy numbers, percentages, amounts, periods and dates exactly as they appear in the passages.
- Always name the scheme (e.g. "HDFC Mid Cap Fund") the fact belongs to. If several schemes are asked about, give each scheme's fact separately.
- If a figure has an "as on" date or differs by plan (Regular/Direct), say so.
- If passages give different values for different dates or periods, give the most recent one and state its date. Passage headers show each document's date. Monthly factsheets and Fund Facts are newer than the KIM/SID.
- Do not present a regulatory maximum or permissible limit (e.g. "maximum TER") as the scheme's actual figure. If only a limit is stated, say it is a limit, or set status to "not_found".
- If the passages give a value as "Nil" or "Not applicable", report that exactly.
- Answer the question that was asked, completely. If several items answer it (e.g. a scheme has two fund managers), list all of them. Do not substitute a narrower or related fact, e.g. a specialist "overseas investments" manager when the scheme's fund manager is asked, or a past year's actual expenses when the current expense ratio is shown.
- A minimum purchase or application amount that applies to all purchases may be given for a minimum SIP question only if you say exactly what the passage states.
- If the passages do not clearly answer the question, or only partly answer it, set status to "not_found". Never guess.
- Never give investment advice, recommendations, suitability opinions or return predictions, even if asked.
- Keep the answer under 90 words, in plain sentences. No markdown, no URLs.
- Cite every passage you used by its id, e.g. ["P2", "P5"].
- Suggest up to 3 short follow-up questions (under 12 words each) that the user might ask next about the same scheme(s) and that the passages can answer. They must be factual (fees, loads, managers, benchmark, objective, plans, dates, lock-in, taxation), never about whether to invest, and different from the question just asked. If several schemes are involved, name the scheme in each follow-up.

Respond with a JSON object only:
{"status": "answered" or "not_found", "answer": "<answer text, or empty if not_found>", "citations": ["P1", ...], "follow_ups": ["<question>", ...]}"""


@dataclass
class Passage:
    pid: str
    chunk: Chunk


def build_user_prompt(question: str, schemes: list[Scheme], passages: list[Passage]) -> str:
    names = ", ".join(s.name for s in schemes)
    blocks = []
    for p in passages:
        c = p.chunk
        header = (
            f"[{p.pid}] Scheme: {c.scheme_name} | Document: {DOC_TYPE_LABEL[c.doc_type]} "
            f"| Page {c.page_number} | {c.document_date}"
        )
        blocks.append(f"{header}\n{c.text}")
    return (
        f"Scheme(s) the user is asking about: {names}\n\n"
        f"Question: {question}\n\n"
        "Passages:\n\n" + "\n\n---\n\n".join(blocks)
    )


# A number is either digit groups separated by commas in Indian/Western
# style (1,00,000 or 22,245.78) or a plain run of digits. "26,2026" (a date
# written without a space) is read as two numbers, 26 and 2026, not 262026.
_NUMBER_RE = re.compile(r"(?<![A-Za-z\d])(?:\d{1,3}(?:,\d{2,3})+(?![\d,])|\d+)(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUMBER_RE.findall(text):
        value = raw.replace(",", "").rstrip(".")
        try:
            out.add(f"{float(value):.6f}")
        except ValueError:
            continue
    return out


def _strip_scheme_names(text: str, schemes: list[Scheme]) -> str:
    # "Nifty 50" is part of a name, not a claimed figure.
    for s in schemes:
        text = re.sub(re.escape(s.name), " ", text, flags=re.IGNORECASE)
    return re.sub(r"\bnifty\s*50\b", " ", text, flags=re.IGNORECASE)


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    answer: str = ""
    cited: list[Chunk] | None = None


def verify(reply: dict, passages: list[Passage], schemes: list[Scheme]) -> Verdict:
    status = str(reply.get("status", "")).strip().lower()
    if status != "answered":
        return Verdict(False, "model_not_found")

    answer = reply.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return Verdict(False, "empty_answer")
    answer = re.sub(r"\s+", " ", answer).strip()

    ids = reply.get("citations")
    if not isinstance(ids, list) or not ids:
        return Verdict(False, "no_citations")
    by_id = {p.pid: p.chunk for p in passages}
    cited: list[Chunk] = []
    for pid in ids:
        pid = str(pid).strip().strip("[]")
        if pid not in by_id:
            return Verdict(False, "unknown_citation")
        if by_id[pid] not in cited:
            cited.append(by_id[pid])

    if re.search(r"https?://|www\.", answer, re.IGNORECASE):
        return Verdict(False, "url_in_answer")
    if answer_contains_advice(answer):
        return Verdict(False, "advice_in_answer")

    # Every scheme cited must be one the user asked about, and named.
    asked = {s.id for s in schemes}
    if any(c.scheme_id not in asked for c in cited):
        return Verdict(False, "wrong_scheme")
    for s in {c.scheme_id: c for c in cited}.values():
        short = s.scheme_name.lower().replace("hdfc ", "").replace(" fund", "")
        if short.split(" tax saver")[0] not in answer.lower():
            return Verdict(False, "scheme_not_named")

    evidence = " ".join(
        f"{c.text} {c.document_date} page {c.page_number}" for c in cited
    )
    missing = _numbers(_strip_scheme_names(answer, schemes)) - _numbers(evidence)
    if missing:
        return Verdict(False, "unsupported_number")

    return Verdict(True, answer=answer, cited=cited)


def quote_for(chunk: Chunk, answer: str, width: int = 300) -> str:
    """Pick the part of a chunk that best supports the answer, for display."""
    text = re.sub(r"\s+", " ", chunk.text).strip()
    positions = []
    # Centre on the most specific figure ("0.25" over "3"): single digits
    # occur all over a page and would pick an arbitrary spot.
    numbers = sorted(set(_NUMBER_RE.findall(answer)), key=lambda n: (-len(n), n))
    for raw in numbers:
        i = text.find(raw)
        if i != -1:
            positions.append(i)
            break
    if not positions:
        words = [w for w in re.findall(r"[a-z]{5,}", answer.lower())][:12]
        lowered = text.lower()
        positions = [lowered.find(w) for w in words if lowered.find(w) != -1]
    center = min(positions) if positions else 0
    start = max(0, center - width // 3)
    end = min(len(text), start + width)
    snippet = text[start:end].strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(text) else "")


def citation_for(chunk: Chunk, answer: str) -> dict:
    is_pdf = ".pdf" in chunk.source_url.lower()
    return {
        "title": chunk.source_title,
        "publisher": chunk.publisher,
        "url": chunk.source_url + (f"#page={chunk.page_number}" if is_pdf else ""),
        "document_url": chunk.source_url,
        "document_type": DOC_TYPE_LABEL[chunk.doc_type],
        "scheme": chunk.scheme_name,
        "date": chunk.document_date,
        "page_number": chunk.page_number,
        # The link opens the scheme webpage, not the PDF, when we don't have a
        # verified PDF URL (currently the ELSS Fund Facts). The UI shows this.
        "page_link": is_pdf,
        "quote": quote_for(chunk, answer),
    }
