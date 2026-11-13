"""Document index: build it offline from the PDFs, search it at request time.

Pipeline:
    build (offline, `python build_index.py`)
        PDF → page text (pypdf) → clean → overlapping chunks → tag each chunk
        with its scheme, document type, page, URL and date → data/index/chunks.json
    search (per request)
        filter to the chunks of the requested scheme(s) → TF-IDF cosine
        similarity → small boost for concise document types → top-k passages

Why build offline? Extracting 13 PDFs took ~25 s on every Vercel cold start.
Loading the prebuilt JSON takes well under a second, and the PDFs no longer
need to ship with the serverless function.

Why filter by scheme before ranking? The previous version ranked all schemes
together and then tried to push wrong-scheme chunks down with score
penalties. Filtering first means a passage about another scheme can never be
used for an answer.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from .schemes import SCHEMES, Scheme

PROJECT_DIR = Path(__file__).resolve().parent.parent
DOCUMENTS_DIR = PROJECT_DIR / "data" / "documents"
SOURCES_PATH = PROJECT_DIR / "sources.json"
INDEX_PATH = PROJECT_DIR / "data" / "index" / "chunks.json"

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200

# Short, scheme-specific documents (Fund Facts, factsheet) state facts more
# directly than the 60-page SID, which is mostly generic legal text. A small
# multiplier prefers them when scores are close.
DOC_TYPE_WEIGHT = {"fund_facts": 1.20, "factsheet": 1.15, "kim": 1.10, "sid": 1.0}
# Short, scheme-specific summaries that state facts directly.
KEY_FACT_TYPES = {"fund_facts", "factsheet"}
DOC_TYPE_LABEL = {
    "fund_facts": "Fund Facts", "factsheet": "Monthly Factsheet",
    "kim": "Key Information Memorandum", "sid": "Scheme Information Document",
}

# Expands common shorthand into the wording the documents use. This helps a
# keyword retriever, which only matches words, not meanings.
QUERY_EXPANSIONS = [
    (r"\bter\b|expense|cost|charges?|fees?", "expense ratio total expense ratio TER"),
    (r"lock ?-?in|lockin", "lock-in period lock in statutory lock in"),
    (r"\bsip\b", "SIP systematic investment plan minimum application amount"),
    (r"minimum|min\b|lump ?sum|least amount", "minimum application amount minimum investment amount purchase additional purchase"),
    (r"exit|redeem|redemption|withdraw", "exit load redeemed switched out date of allotment"),
    (r"benchmark|track|index", "benchmark index TRI"),
    (r"risk", "riskometer risk level"),
    (r"manager|manages|managed", "fund manager"),
    (r"objective|aim|goal|invest in", "investment objective asset allocation"),
    (r"\baum\b|size|assets", "assets under management AUM"),
    (r"return|perform|cagr", "performance returns CAGR since inception"),
    (r"inception|launch|start(?:ed)?|allotment", "date of allotment inception date"),
    (r"tax|80c|capital gain", "taxation capital gains section 80C"),
    (r"plan|option|idcw|growth|direct|regular", "plans and options regular plan direct plan growth IDCW"),
    (r"entry load", "entry load"),
]


@dataclass
class Chunk:
    id: str
    scheme_id: str
    scheme_name: str
    doc_type: str
    file_name: str
    source_title: str
    source_url: str
    document_date: str
    publisher: str
    page_number: int
    text: str


def _clean(text: str) -> str:
    text = text.replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split page text into overlapping windows, preferring line breaks.

    The overlap means a fact that straddles a boundary still appears whole in
    at least one chunk.
    """
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + size // 2, end)
            if cut != -1:
                end = cut
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return out


def build_index(documents_dir: Path = DOCUMENTS_DIR, sources_path: Path = SOURCES_PATH) -> list[Chunk]:
    """Extract and chunk every registered document. Used by build_index.py."""
    import logging

    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    sources = {r["file_name"]: r for r in json.loads(sources_path.read_text(encoding="utf-8"))}
    chunks: list[Chunk] = []
    for scheme in SCHEMES.values():
        for doc in scheme.documents:
            meta = sources.get(doc.file_name)
            if not meta or not meta.get("source_url"):
                raise ValueError(f"{doc.file_name} has no official source_url in sources.json")
            reader = PdfReader(str(documents_dir / doc.file_name))
            for page_number, page in enumerate(reader.pages, start=1):
                if doc.pages and page_number not in doc.pages:
                    continue
                for n, piece in enumerate(_split(_clean(page.extract_text() or ""))):
                    chunks.append(Chunk(
                        id=f"{scheme.id}:{doc.doc_type}:p{page_number}:{n}",
                        scheme_id=scheme.id,
                        scheme_name=scheme.name,
                        doc_type=doc.doc_type,
                        file_name=doc.file_name,
                        source_title=meta.get("source_title", doc.file_name),
                        source_url=meta["source_url"],
                        document_date=meta.get("document_date", ""),
                        publisher=meta.get("publisher", "HDFC Mutual Fund"),
                        page_number=page_number,
                        text=piece,
                    ))
    return chunks


def save_index(chunks: list[Chunk], path: Path = INDEX_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(c) for c in chunks], ensure_ascii=False, indent=0) + "\n",
        encoding="utf-8",
    )


class Index:
    """In-memory search over the prebuilt chunks."""

    def __init__(self, chunks: list[Chunk]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        self.chunks = chunks
        self._by_scheme: dict[str, list[int]] = {}
        for i, c in enumerate(chunks):
            self._by_scheme.setdefault(c.scheme_id, []).append(i)
        # Fitted once per process (previously re-fitted on every question).
        # sublinear_tf stops long repetitive SID pages from dominating.
        self._vectorizer = TfidfVectorizer(
            lowercase=True, stop_words="english", ngram_range=(1, 2), sublinear_tf=True,
        )
        self._matrix = self._vectorizer.fit_transform(
            [f"{c.scheme_name} {DOC_TYPE_LABEL[c.doc_type]}\n{c.text}" for c in chunks]
        )

    @staticmethod
    def expand_query(question: str) -> str:
        q = question.lower()
        extra = [words for pattern, words in QUERY_EXPANSIONS if re.search(pattern, q)]
        return question + " " + " ".join(extra)

    def search(self, question: str, scheme: Scheme, k: int = 6) -> list[tuple[Chunk, float]]:
        """Top-k chunks for one scheme, ranked by weighted TF-IDF similarity."""
        return self._ranked(question, scheme)[:k]

    def search_balanced(self, question: str, scheme: Scheme, key_k: int, other_k: int) -> list[tuple[Chunk, float]]:
        """Best passages from the short key-facts documents AND from the long ones.

        Why: the KIM and SID are long and repeat words like "SIP" or "fund
        manager" many times, so they can push the 2-page Fund Facts sheet,
        which states the answer directly, out of the top results. Reserving
        slots for the key-facts documents keeps the direct answer in view.
        Key-facts passages come first.
        """
        ranked = self._ranked(question, scheme)
        key = [r for r in ranked if r[0].doc_type in KEY_FACT_TYPES][:key_k]
        other = [r for r in ranked if r[0].doc_type not in KEY_FACT_TYPES][:other_k]
        return key + other

    def _ranked(self, question: str, scheme: Scheme) -> list[tuple[Chunk, float]]:
        from sklearn.metrics.pairwise import cosine_similarity

        rows = self._by_scheme.get(scheme.id, [])
        if not rows:
            return []
        query = self._vectorizer.transform([self.expand_query(question)])
        scores = cosine_similarity(query, self._matrix[rows]).flatten()
        ranked = sorted(
            ((float(s) * DOC_TYPE_WEIGHT[self.chunks[r].doc_type], r) for s, r in zip(scores, rows)),
            reverse=True,
        )
        return [(self.chunks[r], s) for s, r in ranked if s > 0]


def load_chunks(path: Path = INDEX_PATH) -> list[Chunk]:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python build_index.py` to build the document index."
        )
    return [Chunk(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


@lru_cache(maxsize=1)
def get_index() -> Index:
    return Index(load_chunks())
