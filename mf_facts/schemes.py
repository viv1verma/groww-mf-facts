"""The schemes this prototype covers, and how a question is matched to them.

Why this file exists: the earlier version silently defaulted to HDFC Nifty 50
Index Fund whenever a question used a short name such as "mid cap" or "the
ELSS fund", and returned Nifty 50 facts for a different scheme. Every answer
now starts by resolving the scheme explicitly. If the question names a scheme
we do not cover, we abstain instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    file_name: str
    doc_type: str  # "fund_facts" | "factsheet" | "kim" | "sid"
    # Restrict a multi-scheme document to the pages about this scheme.
    # None means every page belongs to the scheme.
    pages: tuple[int, ...] | None = None


@dataclass(frozen=True)
class Scheme:
    id: str
    name: str
    category: str
    # Lower-case phrases that identify this scheme in a question. They are
    # matched on word boundaries after normalisation (see _normalise).
    aliases: tuple[str, ...]
    # AMFI scheme codes for the growth options, used for live NAV.
    amfi_codes: dict[str, int] = field(default_factory=dict)
    documents: tuple[Document, ...] = ()


SCHEMES: dict[str, Scheme] = {
    s.id: s
    for s in (
        Scheme(
            id="hdfc-nifty-50-index-fund",
            name="HDFC Nifty 50 Index Fund",
            category="Index Fund",
            aliases=("nifty 50 index", "nifty 50", "nifty50", "nifty fifty"),
            amfi_codes={"Regular Plan - Growth": 101525, "Direct Plan - Growth": 119063},
            documents=(
                Document("Fund Facts - HDFC NIFTY 50 Index Fund_Oct 26.pdf", "fund_facts"),
                # The index factsheet covers ~40 schemes. Its contents page
                # (PDF page 8) maps this scheme to pages 9-10. Update this when
                # a new monthly factsheet replaces the file.
                Document("HDFC MF Index Factsheet - September 2026.pdf", "factsheet", pages=(9, 10)),
                Document("KIM - HDFC Nifty 50 Index Fund dated November 21, 2025.pdf", "kim"),
                Document("SID - HDFC Nifty 50 Index Fund dated November 21, 2025.pdf", "sid"),
            ),
        ),
        Scheme(
            id="hdfc-flexi-cap-fund",
            name="HDFC Flexi Cap Fund",
            category="Flexi Cap Fund",
            aliases=("flexi cap", "flexicap", "flexi"),
            amfi_codes={"Regular Plan - Growth": 101762, "Direct Plan - Growth": 118955},
            documents=(
                Document("Fund Facts - HDFC Flexi Cap Fund.pdf", "fund_facts"),
                Document("KIM - HDFC Flexi Cap Fund dated November 21, 2025_1.pdf", "kim"),
                Document("SID - HDFC Flexi Cap Fund dated November 21, 2025_0.pdf", "sid"),
            ),
        ),
        Scheme(
            id="hdfc-mid-cap-fund",
            name="HDFC Mid Cap Fund",
            category="Mid Cap Fund",
            aliases=("mid cap", "midcap", "mid-cap"),
            amfi_codes={"Regular Plan - Growth": 105758, "Direct Plan - Growth": 118989},
            documents=(
                Document("Fund Facts - HDFC Mid Cap Fund.pdf", "fund_facts"),
                Document("KIM - HDFC Mid Cap Fund dated November 21, 2025_1.pdf", "kim"),
                Document("SID - HDFC Mid Cap Fund dated November 21, 2025_1.pdf", "sid"),
            ),
        ),
        Scheme(
            id="hdfc-elss-tax-saver-fund",
            name="HDFC ELSS Tax Saver Fund",
            category="ELSS (Equity Linked Savings Scheme)",
            aliases=("elss", "tax saver", "taxsaver", "tax saving fund", "tax saving scheme"),
            amfi_codes={"Regular Plan - Growth": 101979, "Direct Plan - Growth": 119060},
            documents=(
                Document("Fund Facts - HDFC ELSS - Tax Saver Fund.pdf", "fund_facts"),
                Document("KIM - HDFC ELSS Tax Saver dated November 21, 2025_0.pdf", "kim"),
                Document("SID - HDFC ELSS Tax Saver dated November 21, 2025.pdf", "sid"),
            ),
        ),
    )
}

# Schemes and fund houses we do NOT cover.
#
# _OTHER_SCHEME_PATTERNS name a specific scheme that is not covered. Any match
# means abstain, even if a covered scheme is also named. This stops
# "Nifty Midcap 150" being read as HDFC Mid Cap Fund, or "Nifty 100" as Nifty 50.
_OTHER_SCHEME_PATTERNS = (
    r"nifty\s*(?:100|next\s*50|200|500|midcap\s*150|smallcap\s*250|largemidcap|india|auto|realty|top\s*20|g\s*sec)",
    r"nifty\s*50\s*equal\s*weight", r"nifty50\s*equal\s*weight",
    r"midcap\s*150", r"sensex\s*(?:index\s*)?fund", r"bse\s*500",
    r"(?:small|large|multi|large\s*and\s*mid)\s*cap\s*fund", r"(?:smallcap|largecap|multicap)\s*fund",
    r"(?:balanced\s*advantage|hybrid|liquid|debt|gilt|overnight|arbitrage|focused|value|gold|silver|"
    r"defence|pharma|banking|infrastructure|technology|dividend\s*yield|children\s*s?|retirement)\s*fund",
    r"etf", r"fund\s*of\s*funds?",
)
# _OTHER_CONTEXT_PATTERNS are other fund houses. They only mean
# "unsupported" when the question names none of our covered schemes. That way
# "Does HDFC Flexi Cap hold ICICI Bank?" is still answered, but "What is the
# exit load of SBI Bluechip?" is not answered with the UI-selected scheme.
_OTHER_CONTEXT_PATTERNS = (
    r"sbi", r"icici", r"axis", r"nippon", r"kotak", r"mirae", r"parag\s*parikh", r"ppfas", r"uti",
    r"aditya\s*birla", r"dsp", r"tata", r"motilal", r"quant", r"franklin", r"canara", r"edelweiss",
    r"invesco", r"bandhan", r"hsbc", r"sundaram", r"mahindra", r"navi", r"zerodha", r"groww\s*(?:nifty|fund|mutual)",
    r"bluechip",
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _contains(phrase: str, text: str) -> bool:
    return re.search(r"\b" + re.escape(_normalise(phrase)) + r"\b", text) is not None


@dataclass
class SchemeResolution:
    schemes: list[Scheme]
    unsupported: bool = False  # the question names something we don't cover
    from_question: bool = False  # True if the question itself named the scheme(s)


def resolve_schemes(question: str, selected_scheme_id: str | None = None) -> SchemeResolution:
    """Work out which covered scheme(s) a question is about.

    Order of precedence:
    1. A scheme we don't cover is named → unsupported (abstain).
    2. Covered scheme(s) named in the question → those schemes.
    3. Otherwise the scheme selected in the UI, if any.
    4. Otherwise none → the caller asks the user to choose.
    """
    q = _normalise(question)
    # Find covered schemes first, removing each matched alias from `stripped`
    # so it is not matched again by the patterns for other schemes.
    stripped = q
    found: list[Scheme] = []
    for scheme in SCHEMES.values():
        hit = False
        for alias in sorted(scheme.aliases, key=len, reverse=True):
            pattern = r"\b" + re.escape(_normalise(alias)) + r"\b(?!\s*(?:equal|next))"
            if re.search(pattern, stripped):
                hit = True
                stripped = re.sub(pattern, " ", stripped)
        if hit:
            found.append(scheme)

    # When a covered scheme is named, an index name on its own is usually
    # context, e.g. "Is the mid cap fund benchmarked to Nifty Midcap 150?".
    # It only counts as another scheme if followed by "fund".
    suffix = r"(?:\s+index)?\s+(?:fund|etf|fof)\b" if found else r"\b"
    if any(re.search(r"\b" + p + suffix, q) for p in _OTHER_SCHEME_PATTERNS):
        return SchemeResolution(schemes=[], unsupported=True, from_question=True)
    if not found and any(re.search(r"\b" + p + r"\b", stripped) for p in _OTHER_CONTEXT_PATTERNS):
        return SchemeResolution(schemes=[], unsupported=True, from_question=True)

    if found:
        return SchemeResolution(schemes=found, from_question=True)
    if selected_scheme_id and selected_scheme_id in SCHEMES:
        return SchemeResolution(schemes=[SCHEMES[selected_scheme_id]])
    return SchemeResolution(schemes=[])


def scheme_for_file(file_name: str) -> list[tuple[Scheme, Document]]:
    return [(s, d) for s in SCHEMES.values() for d in s.documents if d.file_name == file_name]
