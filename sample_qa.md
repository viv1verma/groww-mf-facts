# Sample Q&A: expected behaviour

These examples show what the assistant should do. The figures come from the
documents in `data/documents/` (Fund Facts dated October 2026, data as of 30
September 2026; KIM/SID dated 21 November 2025). The exact wording of answers
comes from the LLM and will vary. The figures, the scheme and the cited source
must not. `eval/questions.json` checks these automatically.

## Answered from documents (with a cited page and quote)

| Question | Scheme | Expected facts | Typical source |
|---|---|---|---|
| What is the exit load? | Nifty 50 Index | 0.25% if redeemed/switched out within 3 days of allotment, nil after | Fund Facts, KIM |
| What is the expense ratio? | Nifty 50 Index | Regular 0.41%, Direct 0.26% (as on 30 Sep 2026) | Fund Facts, Index Factsheet p9 |
| What is the minimum SIP amount? | Nifty 50 Index | May answer "minimum purchase Rs. 100 and any amount thereafter", or abstain. The PDFs don't state a minimum SIP explicitly. | Fund Facts, KIM |
| What is the benchmark? | Nifty 50 Index | NIFTY 50 Index (TRI) | Fund Facts, Factsheet p9 |
| Who is the fund manager? | Nifty 50 Index | Nandita Menezes and Arun Agarwal | Fund Facts |
| Exit load for mid cap fund | Mid Cap | 1.00% if redeemed within 1 year, nil after | Fund Facts |
| Benchmark of the flexi cap fund | Flexi Cap | NIFTY 500 Index (TRI) | Fund Facts |
| What is the lock-in period? | ELSS Tax Saver | Statutory lock-in of 3 years | KIM, SID |
| What's the exit load of the ELSS fund? | ELSS Tax Saver | Nil | Fund Facts |

## Live data

| Question | Behaviour |
|---|---|
| What is the latest NAV? | Regular and Direct growth NAVs and NAV date from AMFI's daily file, cited to AMFI. No LLM involved. |

## Should not answer

| Question | Behaviour |
|---|---|
| What is the exit load? *(no scheme selected)* | Asks which scheme |
| Minimum SIP for HDFC Nifty 100 Index Fund? | "Not covered". Never answers with Nifty 50 facts |
| Exit load of SBI Bluechip? | "Not covered" |
| Should I buy this fund? / Is it good for me? / Which is better? | Advice refusal |
| Will this fund give 15% returns next year? | Advice refusal (prediction) |
| My PAN is …, show my capital gains | Personal-data warning. Message not processed |
| Where can I download my capital gains statement? | Abstains with links to official documents (not in the corpus yet) |
| What is the riskometer level? | Answers only if the level is in extractable text, otherwise abstains |
