import streamlit as st
from functools import lru_cache

from retrieval import load_pdf_chunks, answer_question as retrieve_answer

st.set_page_config(page_title="Groww MF Facts", page_icon="📘", layout="centered")

ADVICE_TERMS = [
    "should i buy", "should i sell", "buy or sell", "should i invest",
    "is this a good investment", "best mutual fund", "recommend a fund",
    "which fund should", "my portfolio", "portfolio allocation",
    "where should i invest", "will it give returns", "predict returns",
    "target return", "which mutual fund is best", "suggest a fund",
]

ADVICE_RESPONSE = (
    "I can provide factual information from official scheme documents, but I can’t "
    "recommend whether you should buy, hold, or sell or suggest a portfolio. "
    "Please consult a SEBI-registered investment adviser for personalised advice."
)

@st.cache_resource(show_spinner="Reading official documents…")
def get_chunks():
    return load_pdf_chunks()

def answer_question(question: str):
    q = question.lower().strip()
    if not q:
        return None

    if any(term in q for term in ADVICE_TERMS):
        return {
            "answer": ADVICE_RESPONSE,
            "source_url": None,
            "source_title": None,
            "document_date": None,
            "page_number": None,
            "refusal": True,
        }

    chunks = get_chunks()
    result = retrieve_answer(question, chunks=chunks)
    if not result:
        return {
            "answer": (
                "I’m sorry, but I couldn’t find a reliable answer to that in the "
                "official documents I currently have available. I don’t want to give "
                "you incorrect information. You could try another question about the "
                "fund, or check HDFC Mutual Fund’s official scheme documents for the "
                "latest details."
            ),
            "source_url": None,
            "source_title": None,
            "document_date": None,
            "page_number": None,
            "refusal": False,
            "unverified": True,
        }

    return {
        "answer": result["answer"],
        "source_url": result["source_url"],
        "source_title": result["source_title"],
        "document_date": result["document_date"],
        "page_number": result.get("page_number"),
        "refusal": False,
    }

st.title("📘 Groww MF Facts")
st.caption("Independent prototype • Official-source facts only")

st.write(
    "Ask factual questions about HDFC Nifty 50 Index Fund. "
    "Answers are retrieved from the official PDF documents loaded into this prototype."
)
st.info(
    "Facts-only. No investment advice. Never enter PAN, Aadhaar, account numbers, "
    "OTPs, email addresses, or phone numbers."
)

examples = [
    "What is the exit load of HDFC Nifty 50 Index Fund?",
    "What is the expense ratio?",
    "What is the benchmark?",
]
st.markdown("**Try an example**")
cols = st.columns(len(examples))
for i, example in enumerate(examples):
    if cols[i].button(example, use_container_width=True):
        st.session_state["question"] = example

question = st.text_input(
    "Your question",
    key="question",
    placeholder="e.g. What is the exit load?",
)

if st.button("Get factual answer", type="primary", use_container_width=True):
    if not question.strip():
        st.warning("Enter a question first.")
    else:
        with st.spinner("Searching the loaded official documents…"):
            result = answer_question(question)
        if result.get("refusal"):
            st.warning(result["answer"])
        else:
            st.markdown("### Answer")
            st.write(result["answer"])

        if result.get("source_url"):
            st.markdown(
                f'**Source:** [{result["source_title"]}]({result["source_url"]})'
            )
            st.caption(f'Last updated from sources: {result["document_date"]}')
            if result.get("page_number"):
                st.caption(f'PDF page: {result["page_number"]}')
        elif result.get("unverified"):
            st.caption("No source citation shown because a supporting source was not retrieved.")

st.divider()
st.caption(
    "Educational prototype only. It is not affiliated with or endorsed by Groww or "
    "HDFC Mutual Fund. Facts can change; verify the linked official document before acting."
)
