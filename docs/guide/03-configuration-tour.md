# 3. Configuration tour

Everything tunable lives in `config.yml` at the repository root. This chapter
groups the knobs by **what they move** — quality, speed, cost, privacy — because
that is how you approach them when tuning. The file's own layout is organized for
the code.

The [last section](#things-you-cannot-configure) lists things you would reasonably
expect to be configurable and are not. It will otherwise cost you an afternoon.

For the exhaustive key-by-key reference, see
[`docs/internal/configuration-reference.md`](../internal/configuration-reference.md).

---

## How configuration works

`config.yml` is bind-mounted into the containers, not baked into the images. The
loader checks the file's modification time on every access and reloads if it
changed, **so most edits take effect without a restart.**

| Change | Needs |
|---|---|
| Most keys | Nothing — save the file |
| Startup-checked values (embedding dimension, reranker cache) | Restart |
| `active.embedding` after documents are ingested | Restart **and full re-ingest** |

That last one matters. Existing vectors came from the old model and are not
comparable to queries embedded by a new one. A startup check refuses to boot on a
dimension mismatch, but it cannot catch a same-dimension swap between different
models — that fails silently as degraded retrieval.

API keys never go in `config.yml`. They are Docker secrets read only from
`/run/secrets/`; an environment variable of the same name is deliberately ignored.
`config.yml` chooses the model, the secret supplies the credential.

Exactly one key is changeable from the running application:
`retrieval.enable_contextual_retrieval`, which the settings page toggles.

---

## Knobs that move quality

### `active.inference` — the model that writes answers

```yaml
active:
  inference: gpt5-mini
```

People reach for this first, and it is usually not the biggest lever. If retrieval
hands the model the wrong passages, a better model writes a better-worded wrong
answer. Check retrieval before upgrading the generator — chapter 7 recipe 1 and 8
separate the two.

Where it does matter: **instruction-following**. The context prompt tells the model
to answer only from the provided passages and to abstain otherwise. Smaller models
follow that less reliably, which shows up as a worse
`abstention_false_negative_rate` — answering confidently when it should decline.

### `active.embedding` — how meaning is matched

```yaml
active:
  embedding: nomic-embed
```

Defines what "similar" means for vector search, so it bounds what the vector half
of hybrid retrieval can find at all. High leverage, most expensive to test —
swapping it invalidates every stored vector.

### `reranker.enabled` and `active.reranker`

```yaml
reranker:
  enabled: true
active:
  reranker: minilm-l6
```

A cross-encoder re-scores candidates by reading each one alongside the question.
Fusion orders by rank position; reranking orders by actual relevance. It is the
most reliable quality lever in the retrieval stage, and it costs latency on every
query.

| Key | Model | Parameters |
|---|---|---|
| `minilm-l6` (default) | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 22.7M |
| `bge-reranker-base` | `BAAI/bge-reranker-base` | 278M |
| `bge-reranker-large` | `BAAI/bge-reranker-large` | 560M |

Larger rerankers generally rank better and are slower. Nothing in this repository
measures the trade-off on your hardware — chapter 7 recipe 7 exists to answer that.

The model must be in the local Hugging Face cache before the server starts. Run
`just init`; the startup check fails fast rather than letting the first query eat a
download.

### `retrieval.top_k` and `reranker.top_n`

```yaml
retrieval:
  top_k: 10        # candidates each search returns, and how many survive fusion
models:
  reranker:
    minilm-l6:
      top_n: 5     # chunks that reach the model after reranking
```

`top_n` is authoritative when set. When omitted it derives as
`max(5, retrieval.top_k // 2)`. The shipped config sets it explicitly to `5`.

Raising `top_k` gives retrieval more chances to include the right passage and gives
the reranker more to work with. Raising `top_n` grows the prompt, which costs
latency and money on every query and can dilute a good answer with marginal
context. Both are genuine trade-offs, and because `top_n` is explicit you can now
vary them independently.

### `retrieval.enable_hybrid_search`

```yaml
retrieval:
  enable_hybrid_search: true
```

Leave it on unless you are deliberately measuring its contribution. Turning it off
does not down-weight keyword search — it routes the query down a structurally
different path that skips BM25 and fusion entirely.

Keyword search is what saves you on rare terms: part numbers, error codes, proper
nouns, anything an embedding model has no useful representation for.

### `retrieval.rrf_k`

```yaml
retrieval:
  rrf_k: 60
```

How sharply rank position is discounted during fusion: a chunk at rank *r*
contributes `1 / (60 + r)`. Because 60 dwarfs a ten-item list, the discount is
nearly flat — rank 1 scores `1/61 = 0.0164` and rank 10 scores `1/70 = 0.0143`,
about 15% apart.

Leave it alone. It is a shape parameter, not a quality dial, and moving it is
unlikely to produce a change you can distinguish from noise.

### `retrieval.enable_contextual_retrieval`

```yaml
retrieval:
  enable_contextual_retrieval: false
```

When on, ingestion asks an LLM to write a one-to-two sentence description of each
chunk — what document it came from, what it discusses — prepended before embedding.
The intent is to rescue chunks meaningless in isolation ("this approach was
rejected for the reasons above").

The cost lands entirely on ingestion: **one LLM call per chunk.** Query-time cost
is unchanged. Treat it as an experiment (chapter 7 recipe 4), not a default.

### `prompts.*`

The system, context, and condense prompts are all editable. The context prompt
carries the weight — it holds the answer-only-from-context instruction and the
exact abstention phrase the model is told to emit.

If you change the abstention wording, **also update `eval.abstention_phrases`**.
The eval framework detects abstention by substring-matching that list. Change one
without the other and the system will look like it stopped abstaining.

---

## Knobs that move speed

Latency is dominated by the generation model and whether the reranker runs.

| Knob | Effect |
|---|---|
| `active.inference` | Largest single factor. A local model on modest hardware can be slower than a cloud round-trip. |
| `reranker.enabled` | A cross-encoder pass on every query. Turning it off is the fastest cut — at a quality cost you should measure. |
| `reranker.top_n` | Prompt length, and therefore tokens to process. |
| `models.inference.<name>.keep_alive` | Ollama only. How long the model stays resident. `10m` shipped; `-1` keeps it loaded forever. |
| `models.inference.<name>.timeout` | 120s default. A ceiling, not a target — raising it changes when you give up, not how fast anything runs. |
| `retrieval.contextual_concurrency` | Ingestion only. Concurrent contextual-prefix LLM calls (default 8). |
| `models.embedding.<name>.embed_batch_size` | Ingestion only. Larger batches ingest faster. |

The first query after a restart is always slower: the reranker model loads lazily
on first use, then stays cached for the process lifetime. Do not include it in a
latency measurement.

---

## Knobs that move cost

Cost exists only with a cloud provider. A local deployment trades money for
hardware and latency.

| Lever | Impact |
|---|---|
| **Provider choice** (`active.inference`, `active.eval`) | Dominant factor |
| **Contextual retrieval** | Largest discretionary cost — one LLM call per chunk, at ingestion. Dwarfs query cost on any real corpus. |
| **`reranker.top_n`** | Sets prompt size, which sets input tokens, which is what you pay per query |
| **`active.eval`** | Three metrics need an LLM call per question. A 100-question run with all metrics means hundreds of judge calls. |

Reported cost is computed from token counts against **hardcoded rate tables in the
source**, not a live pricing feed — and there are two such tables in different
services that have drifted apart. Treat it as an indicator for comparing runs, not
as an invoice.

The config file's own guidance on judges is sound: use a grader at least as capable
as your answer model when you care about subtle faithfulness errors, and a cheaper
one when running at scale. `--no-judge` disables judging entirely when you only
want retrieval metrics (chapter 5).

---

## Knobs that move privacy

### The fundamental choice

Set `active.inference` and `active.embedding` to Ollama-backed models and nothing
leaves your network. That is the strong guarantee; no masking configuration matches
it. Everything below is the weaker case — you want a frontier cloud model and want
to reduce what it sees.

### `pii.enabled`

```yaml
pii:
  enabled: false
```

When on, detected entities in the query, chat history, retrieved context, and
generated session titles are replaced with tokens like `[[[PERSON_0]]]` before
going to a cloud provider, and restored in the response.

Turning it on triggers boot-time validation that **refuses to start** if your
embedding provider is not local. That refusal is intentional: masking the
generation path while shipping raw document text to a cloud embedding API would be
theatre.

### Detection knobs

| Knob | Default | What it does |
|---|---|---|
| `pii.entities` | 7 types | Which entity types to detect. More types, more coverage and more false positives. |
| `pii.score_threshold` | `0.5` | Confidence floor. Lower catches more and masks more things that were not PII. |
| `pii.spacy_model` | `en_core_web_md` | The NER model behind name detection. |
| `pii.gliner.enabled` | `false` | Registers a second, stronger recognizer alongside spaCy at roughly 10× the CPU cost per call. |
| `pii.output_guardrails.block_on_detection` | `false` | Raise rather than return if PII appears verbatim in a response. Cannot apply to streaming. |

### `pii.allow_cloud_judge`

Judge prompts embed retrieved chunks and generated answers **verbatim and
unmasked**. With `pii.enabled` set, the eval service refuses to start against a
cloud judge unless you explicitly set this. Only set it when your evaluation data
contains no real PII.

Chapter 8 covers the threat model properly.

---

## Things you cannot configure

| What | Where it lives | Why it matters |
|---|---|---|
| **Chunk size and overlap** | Hardcoded `chunk_size=500`, `chunk_overlap=50` in `services/rag_server/core/config.py` | Among the highest-leverage RAG parameters, and not in `config.yml` at all. Chapter 7 recipe 3 needs a code edit and image rebuild. |
| **RRF source weights** | Hardcoded to `1.0` / `1.0` | You cannot weight keyword against vector search. Only unweighted RRF is available. |
| **Task worker behaviour** | Six constants in `infrastructure/tasks/task_worker.py` | Poll interval, max attempts, the one-hour stuck-task timeout, retry delays, and a concurrency cap that silently overrides `WORKER_CONCURRENCY`. |
| **Chat-history token budget** | ~50% of the model's context window, with a hardcoded 3000-token fallback | The fallback applies whenever the provider does not report a context window. |

Eval scoring weights and normalization thresholds **are** configurable — see
`eval.scoring` in `config.yml` and chapter 4.

---

## Seeing your current configuration

```bash
just show-config        # active models only
just show-config-full   # adds reranker, retrieval, eval, and PII settings
```

`show-config-full` prints the effective reranker `top_n` alongside the configured
value, e.g. `Top N: 5  (configured: 5)`, so there is no ambiguity about which is in
use. It does **not** print the `database` or `chat_memory` sections — read
`config.yml` for those.

---

**Next:** [4. Evaluation concepts](04-evaluation-concepts.md) — what the metrics
mean before you start moving these knobs.
