# 3. Configuration tour

Everything tunable lives in one file at the repository root: `config.yml`. This
chapter walks the knobs that matter, grouped not by where they sit in the file but
by **what they move** — quality, speed, cost, or privacy.

That grouping is deliberate. When you sit down to tune, you have a goal ("answers
are wrong too often", "this costs too much", "queries take four seconds"), and you
need to know which levers act on it. The file's own layout is organized for the
code, not for you.

Two sections at the end are as important as the rest: knobs that *look* real but
do nothing, and things you would reasonably expect to be configurable but are not.
Both will otherwise cost you an afternoon.

---

## How configuration works

`config.yml` is bind-mounted into the containers rather than baked into the
images. The config loader checks the file's modification time on every access and
reloads if it changed, **so most edits take effect without a restart**. Save the
file and the next query picks it up.

Two things do not follow that rule:

- Anything read once at startup — notably the embedding-dimension compatibility
  check and the reranker model-cache check — needs a restart.
- Changing `active.embedding` after documents are ingested requires a **re-ingest**,
  not just a restart. Existing vectors were produced by the old model and are not
  comparable to queries embedded by the new one. There is a startup check that
  refuses to boot on a dimension mismatch, but it cannot catch a same-dimension
  swap between different models — that will fail silently as degraded retrieval.

API keys never go in `config.yml`. They are Docker secrets, mounted as files under
`/run/secrets/`. The loader reads *only* those files — an environment variable of
the same name is deliberately ignored. `config.yml` chooses which model to use;
the secret supplies the credential.

Exactly one key can be changed through the running application rather than by
editing the file: `retrieval.enable_contextual_retrieval`, which the settings page
toggles. Everything else is an editor.

For the exhaustive key-by-key reference, see
[`docs/internal/configuration-reference.md`](../internal/configuration-reference.md).
This chapter is the opinionated tour.

---

## Knobs that move quality

### `active.inference` — the model that writes answers

```yaml
active:
  inference: gpt5-mini
```

Points at one of the entries under `models.inference`. Local models (Ollama) and
cloud models (OpenAI, Anthropic, Google, DeepSeek, Moonshot) are configured the
same way; only the provider differs.

This is the knob people reach for first, and it is usually not the one that helps
most. If retrieval hands the model the wrong passages, a better model produces a
better-written wrong answer. Check retrieval quality before you upgrade the
generator — chapter 7 has a recipe that separates the two.

Where it *does* matter: instruction-following. The context prompt tells the model
to answer only from the provided passages and to abstain otherwise. Smaller models
follow that instruction less reliably, which shows up as a worse abstention false
negative rate — answering confidently when it should have declined.

### `active.embedding` — how meaning is matched

```yaml
active:
  embedding: nomic-embed
```

Determines what "similar" means for vector search, and therefore what the vector
half of hybrid retrieval can find at all. High-leverage, but the most expensive
change to test: swapping it invalidates every stored vector and requires
re-ingesting your corpus.

### `reranker.enabled` and `active.reranker`

```yaml
reranker:
  enabled: true

active:
  reranker: minilm-l6
```

The reranker is a cross-encoder that re-scores retrieved candidates by reading
each one alongside the question. Fusion orders candidates by rank position;
reranking orders them by actual relevance. It is the single most reliable quality
lever in the retrieval stage, and it costs latency on every query.

The shipped model is `cross-encoder/ms-marco-MiniLM-L-6-v2` — small and fast.
`BAAI/bge-reranker-base` and `bge-reranker-large` are pre-configured alternates.
Larger rerankers generally rank better and are slower; there is no measurement in
this repository telling you the trade-off on your hardware, which is exactly the
kind of question chapter 7 exists to answer.

The reranker model must be present in the local HuggingFace cache before the
server starts — run `just init`. The startup check fails fast rather than letting
the first query eat a model download.

### `retrieval.top_k`

```yaml
retrieval:
  top_k: 10
```

How many chunks each search returns, and how many survive fusion. It also
silently sets the reranker's output size, which is computed as
`max(5, top_k / 2)` — so with the default `10`, five chunks reach the model.

Raising `top_k` gives retrieval more chances to include the right passage and
gives the reranker more to work with. It also grows the prompt, which costs
latency and money on every query, and can dilute a good answer with marginally
relevant context. It is a genuine trade-off rather than a free win.

Note the coupling: `top_k` is the only way to change how many chunks reach the
model. See the dead-config section below for why the obvious knob does not work.

### `retrieval.enable_hybrid_search`

```yaml
retrieval:
  enable_hybrid_search: true
```

On by default, and you should leave it on unless you are deliberately measuring
its contribution. Turning it off does not merely down-weight keyword search — it
routes the query down a structurally different code path that skips BM25 and
fusion entirely.

Keyword search is what saves you on rare terms: part numbers, error codes, proper
nouns, anything an embedding model has no useful representation for.

### `retrieval.rrf_k`

```yaml
retrieval:
  rrf_k: 60
```

Controls how sharply rank position is discounted during fusion. A chunk at rank
*r* contributes `1 / (60 + r)`. Because 60 is large relative to a ten-item list,
the discount across those ten positions is fairly gentle — rank 1 and rank 10
differ by less than a factor of two.

In practice this is a knob to leave alone. It is a shape parameter, not a quality
dial, and moving it is unlikely to produce a change you can distinguish from
noise on a small evaluation set.

### `retrieval.enable_contextual_retrieval`

```yaml
retrieval:
  enable_contextual_retrieval: false
```

Off by default. When on, ingestion asks a language model to write a one-to-two
sentence description of each chunk — what document it came from and what it
discusses — which is prepended before embedding. The intent is to rescue chunks
that are meaningless in isolation ("this approach was rejected for the reasons
above").

The cost is real and lands entirely on ingestion: **one LLM call per chunk.** On
a large corpus with a cloud model this is the most expensive thing the system
does. Query-time cost is unchanged.

This is the one quality knob where the toggle is exposed in the UI as well as the
file. Treat it as an experiment (chapter 7), not a default.

### `prompts.*`

The system prompt, the context prompt, and the condense prompt are all editable.
The context prompt is the one that carries weight: it contains the
answer-only-from-context instruction and the exact abstention phrase the model is
told to emit.

If you change the abstention wording, know that the eval framework detects
abstention by matching against a phrase list — and that list lives in code, not in
the config key that appears to control it. Changing the prompt's phrase without
changing the metric's list will make the system look like it stopped abstaining.

---

## Knobs that move speed

Latency is dominated by two things: the generation model, and whether the reranker
runs.

| Knob | Effect on latency |
|---|---|
| `active.inference` | Largest single factor. A local model on modest hardware can be slower than a cloud API call, network round-trip included. |
| `reranker.enabled` | Adds a cross-encoder pass over the candidates on every query. Turning it off is the fastest way to cut per-query time — at a quality cost you should measure rather than assume. |
| `retrieval.top_k` | More chunks means a longer prompt and more tokens to process. |
| `models.inference.<name>.keep_alive` | Ollama only. How long a model stays resident in memory. Set too short, and you pay the model load on the next query. `10m` is the shipped default; `-1` keeps it loaded indefinitely. |
| `models.inference.<name>.timeout` | 120 seconds by default. A ceiling, not a target — raising it does not make anything faster, it just changes when you give up. |
| `retrieval.contextual_concurrency` | Ingestion only. How many contextual-prefix LLM calls run at once. Raise for faster ingestion if your provider tolerates it. |
| `models.embedding.<name>.embed_batch_size` | Ingestion only. Larger batches ingest faster. |

The first query after a restart is always slower than subsequent ones: the
reranker model is loaded lazily on first use and then cached for the life of the
process. Do not mistake that for a configuration problem, and do not include it in
a latency measurement.

---

## Knobs that move cost

Cost only exists if you use a cloud provider. A fully local deployment trades
money for hardware and latency.

**Provider choice** (`active.inference`, `active.eval`) is the dominant factor.
The per-model rates the system uses for cost reporting are hardcoded tables in the
source, not a live pricing feed — and there are two of them, in different
services, which have drifted apart. Treat reported cost as an indicator for
comparing runs, not as an invoice.

**Contextual retrieval** is the largest discretionary cost in the system: one LLM
call per chunk, at ingestion. On a corpus of any size this dwarfs query cost.

**`retrieval.top_k`** sets prompt size, which sets input tokens, which is what you
pay for on every single query. Halving `top_k` roughly halves the context portion
of your token bill.

**`active.eval`** is the judge model, and evaluation is not free. Three of the
metrics require an LLM call per question, so a 100-question run with all metrics
enabled means hundreds of judge calls. The config file's own guidance is sound:
use a grader at least as capable as your answer model when you care about subtle
faithfulness errors, and a cheaper model when you are running at scale. Note that
you can disable judging entirely with `--no-judge` when you only care about
retrieval metrics — chapter 5 covers this.

---

## Knobs that move privacy

### The fundamental choice

Set `active.inference` and `active.embedding` to Ollama-backed models and nothing
leaves your network. That is the strong guarantee, and no masking configuration
matches it.

Everything below is about the weaker case: you want a frontier cloud model and
want to reduce what it sees.

### `pii.enabled`

```yaml
pii:
  enabled: false
```

Off by default. When on, detected entities in the query, chat history, retrieved
context, and generated session titles are replaced with tokens like
`[[[PERSON_0]]]` before the text goes to a cloud provider, and restored in the
response.

Turning this on triggers boot-time validation that will refuse to start the system
in unsafe combinations — specifically, if your embedding provider is not local.
That refusal is intentional: masking the generation path while shipping raw
document text to a cloud embedding API would be theatre.

### The detection knobs

| Knob | Default | What it does |
|---|---|---|
| `pii.entities` | 7 types | Which entity types to detect. Adding types increases coverage and false positives. |
| `pii.score_threshold` | `0.5` | Detection confidence floor. Lower catches more and masks more things that were not PII. |
| `pii.spacy_model` | `en_core_web_md` | The NER model behind name detection. `en_core_web_lg` is more accurate and roughly fifteen times larger on disk. |
| `pii.gliner.enabled` | `false` | Registers a second, stronger recognizer alongside spaCy. The project's own note puts it at roughly ten times the CPU cost per call. |
| `pii.output_guardrails.block_on_detection` | `false` | Raise rather than return if PII appears verbatim in a response. Note this cannot apply to streaming — by the time the full response can be scanned, tokens are already sent. |

### `pii.allow_cloud_judge`

Judge prompts embed retrieved chunks and generated answers **verbatim and
unmasked**. With `pii.enabled` set, the eval service refuses to start against a
cloud judge unless you explicitly set this. Only set it when your evaluation
dataset contains no real PII — synthetic questions, for instance.

Chapter 8 covers the threat model properly, including what this tier does not
protect against.

---

## Knobs that look real but do nothing

These keys parse, appear in the file, and in some cases are printed back to you by
the config inspector — but nothing in the running system acts on them. Each one
has cost somebody time.

| Key | What actually happens |
|---|---|
| `models.reranker.<name>.top_n` | **Ignored.** The reranker's output size is computed as `max(5, retrieval.top_k / 2)`. Changing this value has no effect; change `retrieval.top_k` instead. `just show-config-full` prints the configured value, which makes this worse — the number it shows you is not the number in use. |
| `database.max_connections` | **Never read.** The real PostgreSQL limit is hardcoded in `docker-compose.yml`. If you raise one you must hand-edit the other to match. |
| `eval.abstention_phrases` | **Not used for eval scoring.** The abstention metrics fall back to their own hardcoded phrase list. Editing this changes nothing about how abstention is measured. |
| `pii.masking_strategy` | **Dead.** Only one value is legal and nothing branches on it. |
| `pii.validation.max_retries` | **Dead.** The recovery routine runs once, unconditionally. There is no retry loop. |
| `pii.validation.alert_on_failure` | **Dead.** No alerting path exists. |

These are recorded as fixable defects in
[`docs/suggestions.md`](../suggestions.md).

---

## Things you would expect to be configurable but are not

| What | Where it actually lives | Why it matters |
|---|---|---|
| **Chunk size and overlap** | Hardcoded at `chunk_size=500`, `chunk_overlap=50` in `services/rag_server/core/config.py` | Among the highest-leverage RAG tuning parameters, and not in `config.yml` at all. The chunk-size experiment in chapter 7 requires a code edit and an image rebuild. |
| **RRF source weights** | Hardcoded to `1.0` / `1.0` | You cannot weight keyword search against vector search. Classic unweighted RRF is all that is available. |
| **Task worker behaviour** | Six constants in `infrastructure/tasks/task_worker.py` | Poll interval, max attempts, the one-hour stuck-task timeout, retry delays, and a concurrency cap that silently overrides the `WORKER_CONCURRENCY` environment variable. |
| **Eval scoring weights** | Python constants in the eval service | The weighted score's objective weights are not in `config.yml`. |
| **Chat-history token budget** | Derived as ~50% of the model's context window, with a hardcoded 3000-token fallback | The fallback applies whenever the provider does not report a context window. |

---

## Missing provider secrets

`config.yml` offers `gemini-pro`, `deepseek-chat`, and `moonshot-v1`, and the code
reads `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`, and `MOONSHOT_API_KEY`. **No compose
file declares any of them as secrets.** Selecting one of these providers passes
YAML validation and then fails at boot. Using them requires hand-editing a compose
file to add the secret. Treat OpenAI, Anthropic, and Ollama as the supported set.

---

## Seeing your current configuration

```bash
just show-config        # compact: active models only
just show-config-full   # adds retrieval, eval, and PII settings
```

Two caveats. It prints the *configured* reranker `top_n`, which is not the value
in use. And it does not print the `database` or `chat_memory` sections at all —
for those, read `config.yml`.

---

**Next:** [4. Evaluation concepts](04-evaluation-concepts.md) — what the metrics
mean before you start moving these knobs.
