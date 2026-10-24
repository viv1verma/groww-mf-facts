# Groww MF Facts — prototype

An independent, facts-only FAQ prototype for public mutual-fund scheme information. It is not an official Groww integration.

## Scope
- Product concept: Groww MF Facts
- AMC: HDFC Mutual Fund
- Initial scheme: HDFC Nifty 50 Index Fund
- Official source pages:
  - Scheme page: https://www.hdfcfund.com/explore/mutual-funds/hdfc-nifty-50-index-fund/regular
  - September 2026 Index Factsheet: https://files.hdfcfund.com/s3fs-public/2026-10/HDFC%20MF%20Index%20Factsheet%20-%20September%202026.pdf?VersionId=ifZn2abNfFlERun_stwnoMdkld729b5o

## Setup
1. Install Python 3.10 or newer.
2. Create and activate a virtual environment.
3. Install dependencies:
   `pip install -r requirements-local.txt`
4. Run the HTML frontend with its local Python API:
   `python api.py`
   Then open `http://127.0.0.1:8000`.
5. To run the existing Streamlit interface instead:
   `streamlit run app.py`

## Tests
Run the retrieval and local API tests with:
`python -m unittest test_retrieval test_api`

The API serves `index.html` and accepts `POST /api/ask` with a JSON body such as
`{"question":"What is the exit load?"}`. Responses include `answer`, source
metadata (`source_url`, `source_title`, `document_date`), `page_number` when
available, and a `refusal` flag for advice requests. It binds to localhost only.

## Vercel deployment
The root `index.html` is served as a static page and `api/ask.py` exposes the
same `POST /api/ask` behavior as a Vercel Python Function. The PDFs and source
catalogs are bundled with that function for the existing retrieval code.
`requirements.txt` contains only deployment dependencies; install
`requirements-local.txt` for the local Streamlit interface as well. Use
`vercel dev` to preview the deployment locally and `vercel --prod` to deploy.

## Prototype behaviour
- Gives short factual answers for selected topics, through the existing retrieval backend.
- Includes one official source link per answer.
- Displays a source/document date or the date the web page was checked.
- Refuses common investment-advice questions.
- Does not ask for or store personal/account information.
- Does not calculate or compare returns.

## Important limitations
- This is a local keyword-retrieval baseline, not a production-grade RAG system.
- It contains a small hand-curated fact set, not the full 15–25 page corpus yet.
- It does not crawl the source pages live. The facts can become stale; verify the linked source before relying on them.
- Unsupported questions receive a conservative fallback response without a citation.
- Advice refusal keyword coverage is not exhaustive.
- The September 2026 factsheet gives the base expense ratio for specified expense components; this should not be misrepresented as every possible TER measure.
- No personal data should be entered. The app does not need PAN, Aadhaar, account details, OTPs, email or phone numbers.

## Disclaimer used in the UI
"Facts-only. No investment advice. Never enter PAN, Aadhaar, account numbers, OTPs, email addresses, or phone numbers."

"Educational prototype only. It is not affiliated with or endorsed by Groww or HDFC Mutual Fund. Facts can change; verify the linked official document before acting."

## Next steps for a stronger RAG implementation
1. Expand the approved corpus to 15–25 official AMC/SEBI/AMFI documents.
2. Store source title, URL, document date, fetched date, scheme, and topic for every document.
3. Chunk documents and retrieve only from the approved corpus.
4. Require each answer to cite a retrieved chunk; otherwise abstain.
5. Add tests for factual questions, unsupported questions, advice refusals, stale sources, and citations.
6. Add an explicit allowlist for official domains and avoid third-party blogs.
