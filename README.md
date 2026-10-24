# Groww MF Facts

A facts-only mutual fund FAQ prototype that answers selected questions
using a curated set of official HDFC Mutual Fund documents. The app
provides source links with supported answers and avoids personalized
investment recommendations.

> **Disclaimer:** This is an independent educational prototype. It is
> not affiliated with, endorsed by, or integrated with Groww or HDFC
> Mutual Fund. Information may change; verify the linked official source
> before relying on it.

## Contents

-   [Overview](#overview)
-   [Features](#features)
-   [How it works](#how-it-works)
-   [Data sources](#data-sources)
-   [Project structure](#project-structure)
-   [Run locally](#run-locally)
-   [Run tests](#run-tests)
-   [API endpoints](#api-endpoints)
-   [Deploy on Vercel](#deploy-on-vercel)
-   [Limitations](#limitations)
-   [Privacy and safe use](#privacy-and-safe-use)

## Overview

  Item            Details
  --------------- --------------------------------------------------------
  Project         Groww MF Facts
  Type            Educational FAQ prototype
  AMC covered     HDFC Mutual Fund
  Initial focus   HDFC Nifty 50 Index Fund
  Frontend        HTML, CSS and JavaScript
  Local API       Python standard-library HTTP server
  Hosted API      FastAPI on Vercel
  Retrieval       Local PDF text extraction and TF-IDF similarity search

The interface is designed to answer factual questions about scheme
documents---not to tell users which fund to buy or sell.

## Features

-   Answers selected factual questions from the available scheme
    documents.
-   Shows an official source link and available document metadata with
    supported answers.
-   Returns a conservative fallback when it cannot find a reliable
    answer in the available material.
-   Refuses personalized investment-advice requests.
-   Includes a lightweight browser-based chat interface.
-   Includes tests for retrieval and API behaviour.

## How it works

1.  The user submits a question in the web interface.
2.  The API checks for advice-seeking requests and handles them with a
    refusal.
3.  For factual questions, the retrieval module searches the extracted
    PDF text using TF-IDF similarity.
4.  When a supported answer is found, the app returns the answer and its
    source metadata.
5.  When the available material does not support a reliable answer, the
    app abstains rather than inventing one.

This is a lightweight retrieval baseline; it is not a production-grade
or generative RAG system.

## Data sources

The project stores curated PDFs in `data/documents/` and source metadata
in `sources.csv` and `sources.json`.

Official starting points include:

-   [HDFC Nifty 50 Index Fund --- scheme
    page](https://www.hdfcfund.com/explore/mutual-funds/hdfc-nifty-50-index-fund/regular)
-   [HDFC MF Index Factsheet --- September 2026
    (PDF)](https://files.hdfcfund.com/s3fs-public/2026-10/HDFC%20MF%20Index%20Factsheet%20-%20September%202026.pdf?VersionId=ifZn2abNfFlERun_stwnoMdkld729b5o)

The app does not crawl these pages live. Its answers are based on the
local corpus and configured retrieval logic, so facts can become stale.
Check the cited official source for the latest information.

## Project structure

``` text
groww-mf-facts/
├── api/
│   ├── ask.py             # Legacy Vercel adapter retained in the repository
│   ├── health.py          # Health endpoint
│   └── index.py           # FastAPI app for Vercel
├── data/
│   └── documents/         # Curated official PDF documents
├── index.html             # Browser frontend
├── api.py                 # Local HTTP API and static-file server
├── app.py                 # Existing Streamlit interface
├── retrieval.py           # PDF extraction, chunking and TF-IDF retrieval
├── sources.csv             # Human-readable source catalog
├── sources.json            # Source metadata used by the app
├── requirements.txt        # Hosted API dependencies
├── requirements-local.txt  # Dependencies for local development interface
├── test_api.py             # API tests
├── test_retrieval.py       # Retrieval tests
├── vercel.json             # Vercel function configuration
└── pyproject.toml           # Python project metadata and dependencies
```

## Run locally

### Requirements

-   Python 3.10 or newer
-   A terminal

### Setup

From the project directory, create and activate a virtual environment:

``` bash
python3 -m venv .venv
source .venv/bin/activate
```

Install local dependencies:

``` bash
pip install -r requirements-local.txt
```

Start the local HTML frontend and API:

``` bash
python api.py
```

Open <http://127.0.0.1:8000> in your browser.

The local server binds to `127.0.0.1`, so it is intended for local
development.

The repository also retains a Streamlit interface. To run it instead,
use:

``` bash
streamlit run app.py
```

## Run tests

With the virtual environment activated, run:

``` bash
python -m unittest test_retrieval.py test_api.py
```

The tests cover retrieval behaviour, API responses, fallback behaviour
and advice refusals.

## API endpoints

### `GET /api/health`

Returns a small health response:

``` json
{"ok": true}
```

### `POST /api/ask`

Request body:

``` json
{
  "question": "What is the benchmark?"
}
```

A supported answer can include these fields:

-   `answer` --- answer text
-   `source_url` --- official source link
-   `source_title` --- source title
-   `document_date` --- source/document date when available
-   `page_number` --- page number when available
-   `refusal` --- whether the response is an advice refusal

If the available documents do not support a reliable answer, the API
returns a conservative fallback without a source citation. The API also
validates request size and question length.

## Deploy on Vercel

The project is configured for GitHub-connected Vercel deployment.

1.  Push the project to the connected GitHub repository.
2.  In Vercel, import the repository or open the existing project.
3.  Keep the project root set to the directory containing `vercel.json`.
4.  Deploy and wait for the build to finish.
5.  Check the health endpoint at `/api/health`.
6.  Open the homepage and test a supported factual question, an
    unsupported question and an advice-seeking question.

The hosted FastAPI entry point is `api/index.py`. The configuration
includes the PDF corpus and source catalogs for retrieval. If a
deployment fails, inspect the Vercel build and runtime logs before
changing code.

## Limitations

-   The corpus is curated and limited; it is not a comprehensive
    mutual-fund knowledge base.
-   Retrieval uses TF-IDF similarity over locally extracted PDF text,
    not a vector database or a live search engine.
-   The app does not crawl official source pages for updates.
-   Some questions may not be answerable from the available documents;
    the expected behaviour is to abstain.
-   Advice-refusal detection uses a finite set of terms and is not
    exhaustive.
-   Expense-ratio terminology can vary by scheme and document; do not
    treat one stated expense component as every possible
    total-expense-ratio measure.
-   Passing the existing tests does not guarantee that every possible
    answer is correct or that every deployment environment will behave
    identically.

## Privacy and safe use

-   Do not enter PAN, Aadhaar, account numbers, OTPs, email addresses,
    phone numbers or other personal/account information.
-   The prototype is intended for public scheme facts, not
    account-specific support.
-   It does not calculate or compare investment returns.
-   It does not provide personalized investment advice. Consult a
    SEBI-registered investment adviser for personalized recommendations.

## Disclaimer

**Facts-only. No investment advice.**

Educational prototype only. It is not affiliated with or endorsed by
Groww or HDFC Mutual Fund. Scheme information can change; verify the
linked official document or scheme page for the latest details.
