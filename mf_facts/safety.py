"""Checks that run before anything is retrieved or sent to the LLM.

1. Personal data: if a question contains something that looks like a PAN,
   Aadhaar, phone number, email or OTP, we stop and never send it to the LLM.
2. Personalised advice: buy/sell/hold, "is it good for me", return
   predictions and portfolio questions are refused politely.

The rules are deliberately broad. Refusing a borderline factual question is a
smaller harm than giving investment advice. The LLM prompt repeats the same
rule as a second layer.
"""
from __future__ import annotations

import re

ADVICE_RESPONSE = (
    "I can share factual information from official scheme documents, but I can't tell you "
    "whether to buy, hold, sell or switch, whether a fund suits you, or what it will return. "
    "For personalised advice, please consult a SEBI-registered investment adviser."
)

PII_RESPONSE = (
    "Please don't share personal details such as PAN, Aadhaar, phone numbers, email "
    "addresses, folio numbers or OTPs here. I only answer general questions about scheme "
    "facts, and I haven't processed your message. Please rephrase it without the personal details."
)

_ADVICE_PATTERNS = [
    # Direct decisions
    r"\bshould i\b",
    r"\bshall i\b",
    r"\bdo you (?:recommend|suggest|advise)\b",
    r"\b(?:recommend|suggest|advise)\b.*\b(?:fund|scheme|invest|portfolio|me)\b",
    r"\b(?:buy|sell|hold|exit|redeem|switch)\b (?:it |this |the fund )?(?:or not|now or later|or wait)\b",
    r"\bbuy or sell\b",
    r"\b(?:worth|wise|safe|smart|right time|good time) (?:to )?(?:invest|buy|enter)",
    r"\bworth (?:it|investing|buying)\b",
    # Suitability
    r"\b(?:good|bad|right|suitable|safe|ideal|best) (?:for me|choice|option|investment|pick)\b",
    r"\bgood fund\b",
    r"\b(?:suit|suits|suitable for|fit|fits|right for|good for|ok for|okay for) me\b",
    r"\bfor my (?:goal|goals|retirement|child|children|family|wife|husband|age|risk)\b",
    r"\bmy (?:portfolio|allocation|savings|salary|money|goal|goals|risk (?:profile|appetite))\b",
    r"\bportfolio (?:allocation|mix|rebalanc)",
    r"\bhow much (?:should|can|must) i\b",
    r"\bwhere (?:should|can|do) i (?:invest|put)\b",
    r"\b(?:put|park|invest) (?:my )?(?:money|savings|lump ?sum)\b",
    # Ranking / comparison for choosing
    r"\bwhich (?:one|fund|scheme|is better|should)\b(?! manager)",
    r"\b(?:better|best|top) (?:fund|scheme|than|option|mutual fund)",
    r"\bis (?:it|this|that) better\b",
    r"\bvs\.? .*\bbetter\b",
    # Return predictions and promises
    r"\b(?:will|would|can) (?:it|this|the fund|they)\b.{0,40}\b(?:return|give|grow|double|triple|make|earn|beat|outperform|crash|fall|rise)",
    r"\b(?:predict|forecast|expected|future|guaranteed|assured) returns?\b",
    r"\breturns? (?:next|in the next|in coming|by 20)\b",
    r"\bhow much (?:will|would) i (?:get|earn|make)\b",
    r"\btarget (?:return|price|nav)\b",
    # Market or price predictions
    r"\bwhat will (?:the )?(?:nifty|sensex|market|markets|index|nav|price|value|returns?)\b",
    r"\b(?:tomorrow|next (?:week|month|quarter|year))\b.{0,30}\b(?:price|nav|close|level|value|return)",
    r"\b(?:price|nav|close|level|value|returns?)\b.{0,30}\b(?:tomorrow|next (?:week|month|quarter|year))\b",
]
_ADVICE_RE = [re.compile(p, re.IGNORECASE) for p in _ADVICE_PATTERNS]

_PII_RE = [
    re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", re.IGNORECASE),           # PAN
    re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"),                     # Aadhaar
    re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)"),            # Indian mobile
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),                          # email
    re.compile(r"\botp\b.{0,15}\d{4,8}|\d{4,8}.{0,15}\botp\b", re.IGNORECASE),
    re.compile(r"\bfolio\b.{0,20}\d{5,}", re.IGNORECASE),
    re.compile(r"\b(?:account|a/c|acct)\s*(?:no\.?|number)?\s*[:#]?\s*\d{8,}", re.IGNORECASE),
]


def is_advice_request(question: str) -> bool:
    return any(rx.search(question) for rx in _ADVICE_RE)


def contains_personal_data(question: str) -> bool:
    return any(rx.search(question) for rx in _PII_RE)


# Phrases that must never appear in a generated answer. If they do, the
# answer is dropped. This is a second line of defence behind the prompt.
_ANSWER_ADVICE_RE = re.compile(
    r"\b(?:you should (?:invest|buy|sell|hold|consider)|i (?:recommend|suggest|advise)|"
    r"(?:is|are) a (?:good|great|safe|excellent) (?:investment|choice|option)|"
    r"(?:will|is expected to) (?:give|deliver|generate) .{0,20}returns?)\b",
    re.IGNORECASE,
)


def answer_contains_advice(answer: str) -> bool:
    return _ANSWER_ADVICE_RE.search(answer) is not None
