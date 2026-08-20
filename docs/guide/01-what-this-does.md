# 1. RAG for high-privacy environments

Retrieval-Augmented Generation (RAG) reduces hallucination by making a language
model *read* your documents instead of recalling from training data. It is
probably the most common enterprise use of AI today — and a conventional RAG
deployment leaks internal data to whichever third party serves the model.

RAGBench removes that exposure two ways: run the whole pipeline locally, or mask
personal data before anything reaches OpenAI, Anthropic, or another provider.

A second goal follows from a shift in the field. The trend has moved away from
hunting for one "best" pipeline and toward treating the corpus itself as a design
constraint — recent work on legal, regulatory, and medical RAG keeps finding that
retrieval fails because document structure and pipeline disagree, not because the
model is weak. So RAGBench is modular, and ships the tools to measure *which
stage* needs work on *your* documents.

---

## The problem RAG solves

A general-purpose model does not know your incident reports, contracts, or last
quarter's architecture decisions. Asked about them, it produces something fluent
and wrong.

RAG changes the model's job from "know everything" to "read carefully and
summarize." At query time the system finds the passages most likely to hold the
answer, puts them in the prompt, and instructs the model to answer from those
alone.

This moves where quality comes from. Hand the model the wrong passages and no
amount of model capability rescues the answer — it will faithfully summarize the
wrong thing. **Most RAG quality problems are retrieval problems.** That single
fact determines which knobs are worth your time.

---

## The pieces

| Piece | Port | What it does |
|---|---|---|
| **Web app** | 8000 | Chat, upload, settings, analytics dashboard |
| **RAG server** | 8001 | Retrieval, answer generation, sessions, metrics API |
| **Task worker** | — | Background document processing (same image, different entry point) |
| **Eval service** | 8002 | Runs quality evaluations, stores results |
| **PostgreSQL** | — | Documents, chunks, chat history, task queue, BM25 keyword index |
| **ChromaDB** | — | Vector store — embeddings only |
| **Ollama** | 11434 | Local inference. Runs on your host, not in a container. Optional. |

The eval service has no special privileges. It calls the RAG server over plain
HTTP, exactly as the web app does, so it measures the same code path a real user
hits. That is deliberate: eval results describe the system you are running, not a
test harness approximation of it.

---

## One question, traced end to end

You ask: *What did we decide about connection pooling?*

**1. The question is made standalone.** On a follow-up turn, chat history is
folded in so "what did we decide about it?" becomes the full question. Retrieval
is a search, and searching for "it" finds nothing. Skipped on the first turn.

**2. Two searches run in parallel.**

| Search | Finds | Example |
|---|---|---|
| **Keyword** (BM25 in PostgreSQL) | Literal words — rare terms, IDs, product names, error codes | Documents containing the phrase "connection pooling" |
| **Vector** (ChromaDB) | Meaning | "we sized the QueuePool at ten persistent connections" — no mention of "pooling" |

Each returns its own ranked list of `top_k` candidates (10 by default).

**3. The lists are fused** with Reciprocal Rank Fusion (RRF). Each chunk scores on
its *position* in each list, not on either search's raw score — a BM25 score and a
cosine similarity live on incomparable scales, but positions are comparable. A
chunk ranked 3rd by keyword and 7th by vector accumulates credit from both.

**4. The survivors are reranked.** Fusion only knows about ranks; it never
compares the question against a chunk's actual text. A cross-encoder now reads
each candidate alongside the question and scores real relevance. It is slow per
chunk, which is why it runs on 10 candidates rather than the corpus. The top 5
survive.

**5. The model writes the answer** from those 5 chunks, instructed to use the
provided context only and to say *"I don't have enough information to answer this
question"* rather than guess.

**6. Sources come back with it**, so you can check the answer against what built
it.

Every tuning change moves some part of this path. "Is reranking worth it?" is a
question about step 4.

---

## What ingestion did earlier

When you upload a file:

1. It lands in a shared directory; a row goes into a PostgreSQL queue table.
2. The task worker claims the row with `SKIP LOCKED`, so workers never collide.
3. **Docling** parses it — PDF, DOCX, PPTX, XLSX, HTML, Markdown, AsciiDoc, plain
   text — understanding structure rather than extracting a wall of text.
4. The document is **split into chunks** (whole documents neither fit in a prompt
   nor retrieve usefully).
5. Each chunk is **embedded** into ChromaDB; the chunk text goes to PostgreSQL,
   where the BM25 index covers it.
6. *Optionally, off by default:* a **contextual prefix** is generated per chunk by
   an LLM, describing what the chunk is about. This rescues chunks that are
   meaningless in isolation — at one LLM call per chunk. Chapter 7 treats it as an
   experiment, not a default.

Ingestion is where the time and money go. Querying is cheap by comparison.

---

## What you can change

Almost all of the above is configurable in `config.yml`. The levers fall into four
groups, which is how chapter 3 organizes them:

| Group | Levers |
|---|---|
| **Quality** | Which models, how many chunks retrieved, reranking, contextual retrieval |
| **Speed** | Model choice, local vs cloud, work per query |
| **Cost** | Provider, number of LLM calls, prompt size |
| **Privacy** | Whether anything leaves your network, and what is masked if it does |

These trade against each other constantly. A larger model answers better and costs
more. Reranking improves ordering and adds latency. No configuration wins on all
four axes — which is exactly why measurement matters. The right answer depends on
your documents, your questions, and your constraints, and nobody else's benchmark
can tell you what it is.

---

## The loop this guide teaches

1. **Measure a baseline.** Run an evaluation against your current configuration.
2. **Change exactly one thing.**
3. **Measure again**, under identical conditions.
4. **Decide whether the difference is real** — and worth its cost in latency or
   money.
5. **Keep it or revert it**, and write down why.

Step 4 is where most RAG tuning goes wrong. A number that moved is not the same as
an improvement. Chapter 6 covers telling the difference; chapter 11 is honest
about where this system cannot.

---

## What this is not

- **Not production-hardened.** No authentication outside the server-tier
  deployment, no multi-tenancy, no high availability, no backups for the data
  volumes. It is a research and reference implementation.
- **Not a compliance tool.** PII masking reduces what a provider sees. It
  pseudonymizes rather than anonymizes and makes nothing lawful on its own.
  Chapter 8 is specific.
- **Not a benchmark leaderboard.** The public datasets exercise the pipeline and
  sanity-check changes. A good HotpotQA score says nothing about whether the
  system answers questions about your contracts. Your own golden set is the
  measurement that matters — chapter 5 covers building one.

---

**Next:** [2. Getting running](02-getting-running.md) — deploy, ingest, confirm.

Engineering view: [`docs/internal/architecture.md`](../internal/architecture.md).
