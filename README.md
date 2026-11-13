# Groww MF Facts

A facts-only mutual fund FAQ assistant. It answers questions about four HDFC
Mutual Fund schemes from official scheme documents and shows the exact source
passage behind every answer. It also shows the latest NAV from AMFI's daily
NAV file. When the documents don't support an answer, it says so instead of
guessing, and it never gives personalised investment advice.

> **Disclaimer:** This is an independent educational prototype. It is not
> affiliated with, endorsed by, or integrated with Groww or HDFC Mutual Fund.
> Information may change. Verify the linked official source before relying on it.

## Contents

- [Overview](#overview)
- [How it works](#how-it-works)
- [Trust and safety design](#trust-and-safety-design)
- [Data sources](#data-sources)
- [Project structure](#project-structure)
- [Run locally](#run-locally)
- [Tests and evaluation](#tests-and-evaluation)
- [API endpoints](#api-endpoints)
- [Deploy on Vercel](#deploy-on-vercel)
- [Updating documents](#updating-documents)
- [Limitations](#limitations)
- [Privacy and safe use](#privacy-and-safe-use)

## Overview

| Item | Details |
|---|---|
| Schemes covered | HDFC Nifty 50 Index Fund, HDFC Flexi Cap Fund, HDFC Mid Cap Fund, HDFC ELSS Tax Saver Fund |
| Documents | Fund Facts, Key Information Memorandum (KIM) and Scheme Information Document (SID) for each scheme, plus the Nifty 50 pages of the monthly index factsheet |
| Live data | Latest NAV from AMFI's official daily NAV file |
| Answer generation | An LLM on a free tier (Google Gemini or Groq, configurable) writes answers only from retrieved passages, and the code then checks them |
| Retrieval | Prebuilt chunk index, scheme filtering, TF-IDF similarity search |
| Frontend | Plain HTML, CSS and JavaScript (`index.html`) |
| Backend | FastAPI on Vercel. Python standard-library server for local development |

**Why AMFI and not Groww for live data?** Groww has no public API, and
scraping its app or website would break its terms of service and fail whenever
its pages change. AMFI is the industry body that publishes the official NAVs
that Groww and every other platform show.

## How it works

```text
question
  │
  ├─ 1. validate            non-empty, ≤ 2000 characters
  ├─ 2. personal data?       PAN / Aadhaar / phone / email / OTP / folio → stop, never sent to the LLM
  ├─ 3. advice request?      buy/sell, "good for me", return predictions → polite refusal
  ├─ 4. resolve scheme(s)    from the question, else the scheme picked in the UI
  │                          another scheme or fund house named → "not covered", no guess
  │                          no scheme at all → ask which one
  ├─ 5. NAV question?        → latest NAV from AMFI, exact published figures
  ├─ 6. retrieve             top passages from THAT scheme's documents only
  ├─ 7. generate             LLM answers only from numbered passages and returns JSON
  ├─ 8. verify (in code)     cited passages exist · every number appears in them ·
  │                          scheme is named · no URLs · no advice wording
  ├─ 9. respond              answer + citations (title, page, date, quote, link), or abstain
  └─ 10. follow-ups          up to 3 suggested next questions, checked by the same safety rules
```

**Concepts, mapped to code:**

| RAG concept | Where | Notes |
|---|---|---|
| Document extraction | `mf_facts/index_store.py` `build_index` | `pypdf`, page by page, run offline |
| Chunking | `_split` | 1,200-character windows with 200 overlap, split at line breaks, each tagged with scheme/doc/page |
| Indexing | `data/index/chunks.json` | built once by `python build_index.py`, so no PDF parsing at request time |
| Retrieval | `Index.search` | filter by scheme first, then TF-IDF cosine similarity with query expansion and document-type weighting |
| Generation | `mf_facts/llm.py`, `mf_facts/grounding.py` | OpenAI-compatible chat API, temperature 0, JSON output |
| Grounding check | `grounding.verify` | rejects unsupported numbers, invented citations, wrong schemes, advice |
| Citations | `grounding.citation_for` | built from chunk metadata, never written by the LLM |

TF-IDF matches words, not meanings. "Semantic" embeddings would let
"how long is my money stuck?" match "lock-in period". That's the natural next
step. The query expansions in `index_store.py` are a lightweight stand-in
for now.

## Trust and safety design

- **Scheme first.** Every answer is tied to an explicitly resolved scheme,
  and retrieval only searches that scheme's documents. Questions about
  schemes we don't cover are declined.
- **The LLM is an untrusted writer.** Its JSON reply is checked in code. If
  any figure in the answer is not in the cited passages, the answer is
  discarded and the user sees an abstention with links to the official
  documents.
- **Citations can't be invented.** Source titles, URLs, pages and quotes come
  from document metadata.
- **Live NAV bypasses the LLM.** Structured numbers are shown exactly as AMFI
  publishes them.
- **Follow-up suggestions are checked too.** The LLM suggests next
  questions from the same passages. Any that ask for advice, contain
  personal data, or name another scheme are dropped, and gaps are filled
  from a fixed list of questions the evaluation set has verified.
- **Advice is refused before retrieval.** The LLM prompt repeats the rule, and
  the answer check blocks advice phrasing.
- **Personal data is never processed.** Messages that look like they contain
  PAN, Aadhaar, phone, email, OTP or folio numbers are rejected before any
  external call. Questions are not logged. Only abstention reason codes are logged.

## Data sources

- PDFs: `data/documents/`
- Official URLs and dates for each PDF: `sources.json`, used by the app
- A readable catalog of the same sources: `sources.csv`
- Live NAV: <https://portal.amfiindia.com/spages/NAVAll.txt>

The ELSS Fund Facts PDF's direct download URL could not be verified, so its
citations link to the official scheme page. The UI says so.

## Project structure

```text
groww-mf-facts/
├── api/index.py            # Vercel entry point (FastAPI)
├── api.py                  # Local dev server (standard library), same endpoints
├── build_index.py          # Rebuilds data/index/chunks.json from the PDFs
├── index.html              # Frontend
├── mf_facts/
│   ├── schemes.py          # Covered schemes, aliases, AMFI codes, documents
│   ├── safety.py           # Advice and personal-data rules
│   ├── index_store.py      # Extraction, chunking, index, search
│   ├── llm.py              # OpenAI-compatible LLM client (Gemini / Groq / custom)
│   ├── grounding.py        # Prompt, answer verification, citations
│   ├── followups.py        # Suggested next questions (LLM + checked catalog)
│   ├── live_nav.py         # AMFI NAV client with caching
│   ├── net.py              # HTTPS helper (certificate bundle)
│   └── service.py          # The full question-to-answer pipeline
├── data/
│   ├── documents/          # Official PDFs (only needed to rebuild the index)
│   └── index/chunks.json   # Prebuilt index used by the app
├── eval/
│   ├── questions.json      # Evaluation questions with expected behaviour
│   └── run_eval.py         # Runs them against the real LLM
├── tests/fixtures/         # Sample AMFI NAV file for tests
├── test_pipeline.py        # Safety, scheme, grounding, pipeline, NAV tests
├── test_retrieval.py       # Index and retrieval tests
├── test_api.py             # HTTP tests for both entry points
├── sources.json / sources.csv
├── .env.example
├── vercel.json
└── requirements.txt
```

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then paste your free API key into .env
python api.py               # http://127.0.0.1:8000
```

**Getting a free LLM key** (pick one):

- **Google Gemini:** create a key in Google AI Studio. Set `LLM_PROVIDER=gemini`.
- **Groq:** create a key in the GroqCloud console. Set `LLM_PROVIDER=groq`.

Free tiers have per-minute and per-day request limits. When a limit is
reached, the app says the answer service is busy. It doesn't fall back to
guessing. Free-tier model names change. If the default model is retired, set
`LLM_MODEL` to a current one from your provider's console. Some free tiers
may use prompts to improve the provider's models. This app only sends the
question and public document passages.

Without a key, the app still runs. Live NAV, refusals and scheme checks work,
and document questions return "service not configured".

## Tests and evaluation

```bash
python -m unittest          # 53 tests, ~3 s, no network or API key needed
python eval/run_eval.py     # 34 real questions against your configured LLM
```

The unit tests use a fake LLM to cover both good and bad model behaviour,
including invented figures and citations. The evaluation script reports:

- **PASS:** correct behaviour
- **MISS:** safe but unhelpful (abstained when it could have answered)
- **WRONG:** unsafe (wrong figure, wrong scheme, or answered when it should not). Target: **0**

Run it after changing the prompt, model, retrieval or documents.

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Web app |
| GET | `/api/health` | `{"ok": true, "llm_configured": bool, "llm_provider": ...}` |
| GET | `/api/schemes` | Covered schemes |
| GET | `/api/nav?scheme=<id>` | Latest AMFI NAV for a scheme |
| POST | `/api/ask` | `{"question": "...", "scheme": "<optional scheme id>"}` |

`/api/ask` returns a `kind`, one of `answer`, `nav`, `refusal`, `pii`,
`abstain`, `unsupported`, `clarify`, `unavailable` or `error`. It also returns:

- `answer`
- `schemes`
- `citations`: each with `title`, `url`, `page_number`, `date`, `quote`, `document_type`
- `follow_ups`: up to 3 suggested next questions, each `{"question", "scheme"}`
- `related_documents`, on abstentions
- `scheme_options`, on clarify/unsupported

The older `source_url`, `source_title`, `document_date`, `page_number`,
`refusal` and `unverified` fields are still included.

## Deploy on Vercel

1. In Vercel → Project → Settings → Environment Variables, add
   `LLM_PROVIDER` and `LLM_API_KEY` (Production and Preview).
2. Push the branch. Vercel builds a preview deployment for it.
3. On the preview URL, check `/api/health` shows `"llm_configured": true`,
   then try a factual question, an advice question and a question about an
   uncovered scheme.
4. Merge to `main` to update production.

`api/index.py` is the single serverless function. `vercel.json` bundles
`mf_facts/`, `data/index/`, `sources.json` and `index.html`. The PDFs are
excluded (`.vercelignore`) because the app only reads the prebuilt index.

## Updating documents

1. Put the new PDF in `data/documents/`.
2. Add its official URL and date to `sources.json` (and `sources.csv`).
3. Register it under its scheme in `mf_facts/schemes.py`. For the monthly
   index factsheet, update `pages=` from its contents page.
4. Run `python build_index.py`, then `python -m unittest` and `python eval/run_eval.py`.
5. Commit the PDF, `sources.json` and `data/index/chunks.json`.

## Limitations

- Only four schemes. Questions about others are declined.
- Retrieval is keyword-based (TF-IDF). Unusual wording can miss the right
  passage, and the system then abstains.
- PDF tables are flattened to text, so some values (e.g. riskometer levels
  drawn as images) can't be extracted. The assistant abstains on those.
- Facts are as of each document's date. Only the NAV is live.
- The advice and personal-data rules are pattern-based and not exhaustive.
- Free LLM tiers are rate-limited and their models change.
- Passing tests and evaluations does not guarantee every answer is correct.
  Always verify with the linked source.

## Privacy and safe use

- Do not enter PAN, Aadhaar, account or folio numbers, OTPs, email
  addresses or phone numbers.
- The prototype answers public scheme facts, not account-specific questions.
- It does not calculate or predict returns.
- It does not provide personalised investment advice. Consult a
  SEBI-registered investment adviser for that.

## Disclaimer

**Facts-only. No investment advice.** Educational prototype only. Not
affiliated with or endorsed by Groww or HDFC Mutual Fund. Scheme information
can change. Verify the linked official document for the latest details.
