# 1. What this does

RAGBench answers questions from documents you supply, and it is built so you can
measure whether those answers are any good.

That second half is the unusual part. Most retrieval-augmented generation (RAG)
setups are easy to stand up and almost impossible to evaluate: you ask a few
questions, the answers look plausible, and you ship. When someone later asks
"would a different embedding model be better?", there is no way to answer except
by trying it and squinting. RAGBench exists to make that question answerable for
*your* documents, with numbers you can defend.

This chapter builds the mental model. Later chapters get concrete.

---

## The problem RAG solves

A general-purpose language model knows what was in its training data. It does not
know your incident reports, your contracts, or last quarter's architecture
decisions — and when asked about them it will often produce something fluent and
wrong.

RAG changes the shape of the problem. Instead of asking the model to recall, you
ask it to read. At query time the system finds the passages from your corpus most
likely to contain the answer, puts them in front of the model, and instructs it to
answer from those passages alone. The model's job shrinks from "know everything"
to "read carefully and summarize."

This shifts where quality comes from. If retrieval hands the model the wrong
passages, no amount of model capability rescues the answer — it will faithfully
summarize the wrong thing. **Most RAG quality problems are retrieval problems.**
That is worth internalizing early, because it determines which knobs are worth
your time.

---

## The pieces

Seven components, six of them containers:

| Piece | What it does |
|---|---|
| **Web app** | The UI you use: chat, document upload, settings, and the analytics dashboard. Runs on port 8000. |
| **RAG server** | The engine. Retrieval, answer generation, sessions, and the metrics API. Port 8001. |
| **Task worker** | Processes uploaded documents in the background. Same image as the RAG server, different entry point. |
| **Eval service** | Runs quality evaluations and stores the results. Port 8002. |
| **PostgreSQL** | Documents, chunks, chat history, the ingestion queue — and the keyword search index. |
| **ChromaDB** | The vector store. Embeddings and nothing else. |
| **Ollama** | Local model inference. Runs on your host, not in a container. Optional if you use cloud models for everything. |

The eval service is worth calling out: it is not privileged. It talks to the RAG
server over plain HTTP, exactly as the web app does. When it evaluates a
configuration it is measuring the same code path a real user hits. That is a
deliberate design property — it means eval results describe the system you are
actually running, not a test harness approximation of it.

---

## One question, traced end to end

Suppose you have ingested a set of engineering documents and you type:

> *What did we decide about connection pooling?*

Here is what happens, in order.

**1. The question is made standalone.** If this is a follow-up in an existing
conversation, the system first rewrites it into a self-contained question using
the chat history — "what did we decide about it?" becomes "what did we decide
about connection pooling?" This matters because the retrieval step is a search,
and a search for "it" finds nothing. On the first turn of a conversation this
rewrite is skipped entirely, since there is no history to fold in.

**2. Two searches run, in parallel.**

The *keyword search* looks for the literal words. It runs against a BM25 index in
PostgreSQL and is good at exactly the thing vector search is bad at: rare terms,
identifiers, product names, error codes. If a document contains the phrase
"connection pooling," this search will find it.

The *vector search* looks for meaning. The question is converted into a numeric
embedding, and ChromaDB returns the chunks whose embeddings sit closest to it.
This finds a passage that says "we sized the QueuePool at ten persistent
connections" even though it never uses the word "pooling."

Each search returns its own ranked list of ten candidates.

**3. The two lists are fused.** The system combines them using Reciprocal Rank
Fusion (RRF): each chunk scores based on its *position* in each list rather than
on either search's raw score. A chunk ranked third by keyword search and seventh
by vector search accumulates credit from both. Chunks that only one method found
still make it through, just with less weight.

Rank-based fusion is used because the two scores are not comparable — a BM25
score and a cosine similarity live on different scales with no meaningful
conversion between them. Positions *are* comparable.

**4. The survivors are reranked.** Fusion gives a decent ordering cheaply, but it
never actually compares the question against a chunk's text directly — it only
knows about ranks. So a second-stage model, a cross-encoder, reads each candidate
alongside the question and scores how well it truly answers it. This is slower
per chunk, which is why it runs on ten candidates rather than the whole corpus.
The top five survive.

**5. The model writes the answer.** Those five chunks are pasted into a prompt
that instructs the model to answer from the provided context only, and to say
*"I don't have enough information to answer this question"* rather than guess.
The model generates the answer.

**6. Sources come back with it.** The chunks that fed the answer are returned
alongside it, so you can check the answer against what it was built from. By
default you get one entry per source document.

The whole path — condense, search, fuse, rerank, generate — is what any tuning
change is moving. When you later ask "is reranking worth it?", you are asking
about step 4.

---

## What ingestion did earlier

None of the above works unless documents were processed first. When you upload a
file:

It lands in a shared directory, and a row is written to a queue table in
PostgreSQL. The task worker claims that row — using `SKIP LOCKED` so that
multiple workers never grab the same job — and begins processing.

The document is parsed by **Docling**, which handles PDF, DOCX, PPTX, XLSX, HTML,
Markdown, AsciiDoc, and plain text, and which understands document structure
rather than just extracting a wall of text.

The parsed document is **split into chunks**, because whole documents do not fit
in a prompt and are too coarse to retrieve against usefully.

Each chunk is **embedded** into a vector and stored in ChromaDB. The chunk text
itself is stored in PostgreSQL, where the BM25 index covers it.

Optionally — off by default — a **contextual prefix** is generated for each chunk
by asking a language model to describe what the chunk is about and which document
it came from. This helps retrieval when a chunk is unintelligible in isolation.
It also means one LLM call per chunk, which dominates ingestion time and cost.
Chapter 7 treats it as an experiment rather than a default.

Ingestion is where most of the time and money goes. Querying is cheap by
comparison.

---

## What you can change

Almost every part of that pipeline is configurable in `config.yml`, and the
interesting question is never "can I change this?" but "will changing it help,
and how would I know?"

The levers fall into four groups, which is how chapter 3 organizes them:

- **Quality** — which models, how many chunks retrieved, whether reranking runs,
  whether contextual retrieval runs.
- **Speed** — model choice, local vs cloud, how much work happens per query.
- **Cost** — which provider, how many LLM calls, how large the prompts get.
- **Privacy** — whether anything leaves your network, and what is masked if it
  does.

These trade against each other constantly. A larger model usually answers better
and always costs more. Reranking usually improves ordering and always adds
latency. There is no configuration that wins on all four axes, which is exactly
why measurement matters: the right answer depends on your documents, your
questions, and your constraints, and nobody else's benchmark can tell you what it
is.

---

## The loop this guide teaches

Everything from chapter 4 onward serves one workflow:

1. **Measure a baseline.** Run an evaluation against your current configuration
   and record the result.
2. **Change exactly one thing.**
3. **Measure again**, under identical conditions.
4. **Decide whether the difference is real** — and whether it is worth what it
   cost you in latency or money.
5. **Keep it or revert it**, and write down why.

Step 4 is where most RAG tuning goes wrong, and it is the part this guide spends
the most effort on. A number that moved is not the same as an improvement.
Chapter 6 covers how to tell the difference; chapter 11 is honest about the cases
where this system cannot tell you.

---

## What this is not

Worth stating plainly before you invest time:

- **It is not production-hardened.** There is no authentication outside the
  server-tier deployment, no multi-tenancy, no high availability, and no backup
  mechanism for any of the data volumes. It is a research and reference
  implementation.
- **It is not a compliance tool.** The PII masking tier reduces what a cloud
  provider sees. It pseudonymizes rather than anonymizes, and it does not make
  sending your data to a third party compliant with anything. Chapter 8 is
  specific about the limits.
- **It is not a benchmark leaderboard.** The public datasets it ships with are
  useful for sanity checks and for exercising the pipeline, but a good score on
  HotpotQA tells you nothing about whether the system answers questions about
  your contracts. Your own golden set is the measurement that matters, and
  chapter 5 covers building one.

---

**Next:** [2. Getting running](02-getting-running.md) — deploy the stack, ingest
documents, and confirm it works.

For the engineering view of anything above, see
[`docs/internal/architecture.md`](../internal/architecture.md).
