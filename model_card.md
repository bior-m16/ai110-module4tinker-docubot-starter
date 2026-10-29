# DocuBot Model Card

This model card is a short reflection on your DocuBot system. Fill it out after you have implemented retrieval and experimented with all three modes:

1. Naive LLM over full docs  
2. Retrieval only  
3. RAG (retrieval plus LLM)

Use clear, honest descriptions. It is fine if your system is imperfect.

---

## 1. System Overview

**What is DocuBot trying to do?**  
Describe the overall goal in 2 to 3 sentences.

> _Your answer here._

**What inputs does DocuBot take?**  
For example: user question, docs in folder, environment variables.

> _Your answer here._

**What outputs does DocuBot produce?**

> _Your answer here._

---

## 2. Retrieval Design

**How does your retrieval system work?**  
Describe your choices for indexing and scoring.

- How do you turn documents into an index?
- How do you score relevance for a query?
- How do you choose top snippets?

> _Your answer here._

**What tradeoffs did you make?**  
For example: speed vs precision, simplicity vs accuracy.

> _Your answer here._

---

## 3. Use of the LLM (Gemini)

**When does DocuBot call the LLM and when does it not?**  
Briefly describe how each mode behaves.

- Naive LLM mode:
- Retrieval only mode:
- RAG mode:

> _Your answer here._

**What instructions do you give the LLM to keep it grounded?**  
Summarize the rules from your prompt. For example: only use snippets, say "I do not know" when needed, cite files.

> _Your answer here._

---

## 4. Experiments and Comparisons

Each query below was run word for word through all three modes in one session (Gemini `gemini-flash-lite-latest`, section-level retrieval with IDF weighting and the refusal guardrail).

**What evidence each mode uses**

- **Naive LLM:** none from the docs. `naive_answer_over_full_docs` ignores `all_text` and sends only "You are a documentation assistant. Answer this developer question". It should refuse when it lacks context, but nothing in the prompt tells it to, so it either answers from general knowledge or asks the user for the docs.
- **Retrieval only:** the top sections from `docs/`, printed raw. It should refuse when no section contains at least 2 of the query's meaningful words (see section 5).
- **RAG:** the same retrieved sections, passed to Gemini with a prompt that says to use only the snippets and to refuse when they are not enough. It refuses if retrieval returns nothing (Gemini is never called) or if Gemini decides the snippets do not answer the question.

| Query | Naive LLM | Retrieval only | RAG | Notes |
|------|-----------|----------------|-----|-------|
| Where is the auth token generated? | Harmful-ish: asks which project; no answer | Helpful: `AUTH.md` Token Generation first | Helpful: names `generate_access_token` in `auth_utils.py`, cites `AUTH.md` | Best case for RAG |
| How does a client refresh an access token? | Harmful: confident generic OAuth2 answer (`POST /oauth/token`, `grant_type=refresh_token`, `client_id`) | Helpful but spread over 3 sections in 2 files | Helpful: `/api/refresh` with `Authorization: Bearer <token>`, cites both files | Naive answer does not match this app's API |
| Is there any mention of payment processing in these docs? | Unhelpful: says the docs were not provided | Helpful: refuses | Helpful: refuses ("I do not know based on these docs.") | Naive never saw the docs, so it cannot answer the question it was asked |
| How do I log in? | Harmful: invents a `/login` page, SSO and a "Forgot Password?" link | Before fix: only `AUTH.md` Common Failure Cases (wrong). After fix: `POST /api/login` first | Before fix: false "I do not know". After fix: correct `POST /api/login` answer citing `API_REFERENCE.md` and `AUTH.md` | See failure case 1; fixed by normalizing "log in" to "login" |
| What is the database password? | Unhelpful: asks for the docs | Misleading: returns Connection Configuration (shares "database" and "password") | Helpful (correct refusal) but awkward: "Based on the provided documentation, I do not know based on the docs I have." | The docs contain no password |
| How do I deploy to kubernetes? | Harmful: long, confident Kubernetes tutorial with invented YAML | Helpful: refuses | Helpful: refuses | Nothing about Kubernetes in the docs |

**What patterns did you notice?**

- **Naive generation, confident but weakly grounded:** "How does a client refresh an access token?" gets a polished OAuth2 answer with example requests, but it describes a generic provider endpoint, not this app's `POST /api/refresh`. "How do I deploy to kubernetes?" and "How do I log in?" get equally confident answers that are not in the docs. The naive prompt never includes the docs, so it cannot say "not in the docs".
- **Retrieval only, accurate but hard to read:** for the refresh question it returns the right material (`AUTH.md` Client Workflow, `API_REFERENCE.md` POST /api/refresh, `AUTH.md` Validating Requests), but the reader has to piece the answer together from raw markdown across two files. It never says the endpoint outright.
- **RAG, clarity plus evidence:** "Where is the auth token generated?" gets a one-sentence answer naming the function and module, with `AUTH.md` cited. The refresh question gets a short answer that combines two files and lists both.
- **Retrieval-only is clearly better** when you want to check the evidence yourself, and when the question has no answer (it refuses before any model is involved).
- **RAG is clearly better than both** when the answer is in the docs and spans more than one section.

---

## 5. Failure Cases and Guardrails

**Concrete failure cases observed**

> **Failure case 1: RAG refused an answerable question ("How do I log in?") (fixed).** `POST /api/login` is documented in `API_REFERENCE.md` and `AUTH.md` says to send credentials to `/api/login`. Retrieval matched only the query word "log" (the word "in" is a stopword), and "log" does not match "login", so it returned `AUTH.md` Common Failure Cases, which is unrelated. RAG then correctly refused given that context: "I do not know based on the docs I have." The failure was in retrieval, not in the model: RAG can only be as good as retrieval, and here it turned a retrieval miss into a false refusal. **Fix:** `_tokenize` in `docubot.py` now rewrites "log in", "log-in", "sign in" and "sign-in" to "login" before splitting words. The same question now returns the `POST /api/login` section first, and RAG answers with the endpoint, the request body and the Bearer header, citing both files. The underlying weakness remains for other synonyms and spellings that are not in that rewrite rule.

> **Failure case 2: awkward refusal wording ("What is the database password?").** Retrieval passed the guardrail because the question shares "database" and "password" with `DATABASE.md` Connection Configuration. Gemini refused, which is correct, but wrote "Based on the provided documentation, I do not know based on the docs I have." The refusal is right but self-contradictory. Separately, the guardrail checks word overlap, not whether a section answers the question, so it let a question with no answer through to the model.

> **Failure case 3 (naive mode): confident wrong answer ("How does a client refresh an access token?").** Naive mode answered with a generic OAuth2 flow (`POST /oauth/token`, `grant_type=refresh_token`). The docs say `POST /api/refresh` with an `Authorization: Bearer <token>` header. It should have used the docs.

**When should DocuBot say "I do not know based on the docs I have"?**

- The topic is not in the docs at all (payment processing, Kubernetes deployment, CEO salary). Retrieval finds no section with enough matching words.
- The docs are related to the question but do not contain the specific fact (database password): the model must refuse when the snippets do not answer it.
- The query is empty or has no meaningful words after stopwords are removed.

**What guardrails did you implement?**

- **Retrieval refusal guardrail** (`has_enough_evidence` in `docubot.py`): a section counts as evidence only if it contains at least `MIN_MATCHED_TERMS = 2` distinct query words (all of them, for a one-word query). If no section qualifies, `retrieve` returns nothing and both retrieval-only and RAG print "I do not know based on these docs." In RAG mode the LLM is never called in that case.
- **RAG prompt rules** in `llm_client.py`: use only the snippets, do not invent functions, endpoints or settings, and refuse when the snippets are not enough.
- **Top-3 cap** on snippets, and sections instead of whole files, to keep irrelevant text away from the model.

---

## 6. Limitations and Future Improvements

**Current limitations**  
List at least three limitations of your DocuBot system.

1. _Limitation 1_
2. _Limitation 2_
3. _Limitation 3_

**Future improvements**  
List two or three changes that would most improve reliability or usefulness.

1. _Improvement 1_
2. _Improvement 2_
3. _Improvement 3_

---

## 7. Responsible Use

**Where could this system cause real world harm if used carelessly?**  
Think about wrong answers, missing information, or over trusting the LLM.

> _Your answer here._

**What instructions would you give real developers who want to use DocuBot safely?**  
Write 2 to 4 short bullet points.

- _Guideline 1_
- _Guideline 2_
- _Guideline 3 (optional)_

---
