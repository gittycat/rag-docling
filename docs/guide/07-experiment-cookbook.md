# 7. Experiment cookbook

Eight experiments, each in the same shape: the question, what to change, what to
expect, how to measure, how to read it, and the caveat that will otherwise catch
you out.

All assume the discipline from [chapter 6](06-tuning-workflow.md): establish a
noise floor first (with `--no-judge-cache`), choose your primary metric before you
look at results, and read the confidence interval rather than the delta.

**Any numbers shown are illustrative.** This system ships with no measured
before/after results, and none are invented here.

---

## Choosing your tier

> If what you changed happens **before** the model sees its context, you need
> `end_to_end`. If it happens **after**, `generation` gives a cleaner signal.

| Experiment | Tier | Why |
|---|---|---|
| Reranking on/off | `end_to_end` | In the retrieval path |
| Reranker model swap | `end_to_end` | Same |
| `top_k` / `top_n` | `end_to_end` | Same |
| Hybrid search on/off | `end_to_end` | Same |
| Embedding model | `end_to_end` | Retrieval only |
| Chunk size | `end_to_end` | Ingestion-time |
| Contextual retrieval | `end_to_end` | Ingestion-time |
| Generation model | either | `generation` isolates it; `end_to_end` shows the whole system |

Testing a retrieval change in the `generation` tier measures nothing, and it will
not error — it will report numbers that did not move.

**The golden set only supports the `generation` tier**, so it cannot test retrieval
changes even when you annotate `gold_passages`. Annotations make it measure how
well the pipeline *uses* the right passages. For retrieval experiments use
`ragbench`, `hotpotqa`, or `msmarco` in `end_to_end`.

---

## Recipe 1 — Is reranking worth it?

**Question.** Reranking adds latency to every query. Does the quality justify it on
my corpus?

```yaml
reranker:
  enabled: false
```

**Expect.** Reranking is the most reliable quality lever in the retrieval stage. It
re-scores candidates by reading each one against the question rather than inferring
relevance from rank position. Turning it off should degrade ordering-sensitive
metrics and cut latency.

**Measure.**

```bash
just eval --tier end_to_end --datasets ragbench --samples 50 \
  --seed 42 --name "rerank-on"
# edit config.yml, confirm: just show-config-full
just eval --tier end_to_end --datasets ragbench --samples 50 \
  --seed 42 --name "rerank-off"
just eval-compare <run_a> <run_b>
```

Primary: `recall_at_5` or `mrr` — reranking changes *ordering*, and these are the
ordering metrics. Secondary: `faithfulness`, `latency_p95_ms`.

**Read.** Look for the coherent pattern: `mrr`, `ndcg_at_10`, and `recall_at_5`
moving together, with `faithfulness` following because better-ordered context
produces better-grounded answers. `recall_at_10` should move *less* than
`recall_at_5` — reranking reorders within the candidate pool rather than expanding
it. If only one metric moved, treat it as noise.

**Caveat.** The reranker loads lazily on first use and caches for the process
lifetime, so the first query after a restart includes a one-time model load. Keep
it out of a latency comparison. Note also that with the shipped `top_k: 10` and
`top_n: 5`, reranking narrows 10 candidates to 5 — the more filtering it does, the
larger its impact.

---

## Recipe 2 — Local vs cloud generation model

**Question.** A local model is free and private. What does it cost in quality?

```yaml
active:
  inference: granite4-8b   # was gpt5-mini
```

**Expect.** The gap usually shows in instruction-following rather than raw
knowledge — which matters here, since RAG's premise is that the model reads the
provided context rather than recalling. Watch for the model ignoring "answer only
from the context," and for abstention behaviour degrading.

**Measure.** `generation` tier, to isolate the model from retrieval variance:

```bash
just eval --tier generation --datasets golden --samples 40 \
  --seed 42 --name "cloud-gen"
just eval --tier generation --datasets golden --samples 40 \
  --seed 42 --name "local-gen"
```

Primary: `faithfulness`. Secondary: `answer_correctness`,
`abstention_false_negative_rate`, `latency_p95_ms`, `cost_per_query`.

**Read.** `abstention_false_negative_rate` is the one to watch and the one most
people ignore. It measures how often the model answered a question it should have
refused — that is, made something up. A smaller model scoring slightly worse on
correctness but much worse on false negatives is substantially riskier than the
correctness number alone suggests.

For abstention to be measurable your dataset needs unanswerable questions. Add some
to your golden set with `"query_type": "unanswerable"`, or use `squad_v2`.

**Caveat — judge bias bites hardest here.** The shipped judge is an OpenAI model,
and research on LLM-as-judge documents that judges score their own model family
more favourably even when generator and judge are not identical. Comparing an
OpenAI generator against a local one using an OpenAI judge is **not neutral** and
likely flatters the cloud model. The runner detects this and records a warning on
the run. If the experiment matters, set `active.eval` to an Anthropic model and see
whether the conclusion survives.

Also: local latency depends entirely on your hardware, and the cost tables treat
Ollama models as free — true for marginal cost, silent about the hardware you
bought.

---

## Recipe 3 — Chunk size

**Question.** Are 500-token chunks right for my documents?

**This one requires a code edit.** `chunk_size` and `chunk_overlap` are not in
`config.yml`; they are hardcoded in `services/rag_server/core/config.py`:

```python
Settings.chunk_size = 500
Settings.chunk_overlap = 50
```

Change them, rebuild, **and fully re-ingest** — existing chunks came from the old
settings.

```bash
just build && just up
```

That expense is the main reason to think before running this one.

**Expect.** Coverage against precision. Larger chunks carry more surrounding
context, so a retrieved chunk more likely holds the complete answer — but the
embedding averages over more content, blurring what the chunk is "about." Smaller
chunks match precisely and fragment answers across several chunks.

Published work varies by corpus and task. A controlled biomedical RAG study used
512 tokens with ~10% overlap, citing a precision-recall optimum near 512 — close to
the shipped 500. That is one domain's benchmark, not a general law. Dense reference
tables and long discursive prose do not want the same chunk size.

**Measure.** `end_to_end`, retrieval metrics primary:

```bash
just eval --tier end_to_end --datasets ragbench --samples 50 --seed 42 --name "chunk-500"
# code edit, rebuild, re-ingest
just eval --tier end_to_end --datasets ragbench --samples 50 --seed 42 --name "chunk-250"
```

Primary: `recall_at_5`. Secondary: `precision_at_5`, `faithfulness`.

**Read.** Expect recall and precision to move in opposite directions — that is the
trade-off working as described. `faithfulness` is the tiebreaker, since it reflects
whether the model actually had what it needed.

**Caveat.** Overlap is more contested than it looks. The common assumption is that
overlap preserves context across boundaries, but a systematic segmentation study in
chemistry-aware RAG found its best configuration was 100-token chunks with **zero
overlap**, and reported no measurable benefit from overlap while it raised indexing
cost. Sources genuinely disagree. If you are already paying to re-ingest, testing
`chunk_overlap = 0` costs nothing extra and may be informative.

There is also **no reliable general guidance on how chunk size and reranker
settings should co-vary** — unresolved in the literature, not merely undocumented
here. Vary one at a time.

Source: [Chunk Twice, Embed Once (arXiv:2506.17277)](https://arxiv.org/abs/2506.17277).

---

## Recipe 4 — Contextual retrieval on or off

**Question.** Is one LLM call per chunk at ingestion worth what it buys?

```yaml
retrieval:
  enable_contextual_retrieval: true
```

This is the one key the running application can change — the settings page toggles
it. Either way, **you must re-ingest**: the setting affects how chunks are built.

**Expect.** Each chunk gets a one-to-two sentence generated description of what it
is and where it came from, prepended before embedding. The intent is to rescue
chunks meaningless in isolation — a paragraph beginning "this approach was rejected
for the reasons above" is nearly unretrievable on its own.

Anthropic's published results are the reference point, measured as 1 − recall@20 on
their benchmark:

| Configuration | Failure rate | Reduction |
|---|---|---|
| Baseline | 5.7% | — |
| Contextual embeddings alone | 3.7% | 35% |
| Contextual embeddings + contextual BM25 | 2.9% | 49% |
| ...plus reranking | 1.9% | 67% |

Two things follow. The 49% figure **already assumes hybrid search** — it is not an
additional gain layered on a separate hybrid benefit. And RAGBench ships with
reranking enabled, so your configuration corresponds to the 67% row, not the 49%
one.

Those are Anthropic's numbers on Anthropic's corpus — a reason to run the
experiment, not a prediction of your result.
Source: [Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval).

**Measure.** `end_to_end`, retrieval metrics primary. Also record how long
ingestion took, and what it cost.

**Read.** The cost side decides this. One LLM call per chunk means a 10,000-chunk
corpus costs 10,000 calls, and re-ingesting for any reason costs them again. A
small retrieval improvement may not be worth that against a paid API. If retrieval
is already strong on your corpus, the headroom this targets may not exist.

**Caveat.** Contextual retrieval dominates ingestion time. The claim that it
accounts for roughly 85% of processing time appears in this repository's own notes
and **has never been measured** — the only real benchmark in the repo ran with the
feature disabled. Treat it as architecturally plausible and unverified; measure
your own ingestion time before and after.

Two more: raise `retrieval.contextual_concurrency` (default 8) to speed ingestion
if your provider tolerates the parallelism. And if PII masking is enabled, the
document name and chunk preview are masked before this call, which adds detection
cost per chunk.

---

## Recipe 5 — `top_k` and `top_n`

**Question.** Should I retrieve more candidates, or send more chunks to the model?

```yaml
retrieval:
  top_k: 20          # was 10 — candidates from each search
models:
  reranker:
    minilm-l6:
      top_n: 5       # unchanged — chunks reaching the model
```

**Expect.** These are now separable, and they do different things.

| Knob | Raising it | Costs |
|---|---|---|
| `top_k` | More chances for retrieval to include the right passage, and more for the reranker to choose from | Retrieval and reranking time |
| `top_n` | More context reaches the model | Prompt size on every query — latency and tokens; risks diluting a good answer with marginal context |

Vary one at a time. Raising `top_k` while holding `top_n` at 5 isolates "did
retrieval find it?" from "did the model get it?"

**Measure.** `end_to_end`. Primary: `recall_at_5`. Secondary: `precision_at_5`,
`faithfulness`, `latency_p95_ms`, `cost_per_query`.

**Read.** Compare `recall_at_10` against `recall_at_5` in your baseline first.
**If `recall_at_10` is much higher, the right passage is being found but ranked too
low** — a reranking problem, and raising `top_k` alone will not fix it. If both are
similarly low, retrieval is not finding the passage at all and a larger pool may
genuinely help.

**Caveat.** `cost_per_query` scales roughly with prompt length, so raising `top_n`
should visibly raise it. If it does not, check whether your provider reports token
counts at all — usage is omitted when it does not, which makes cost look flat when
it is not.

---

## Recipe 6 — Embedding model swap

**Question.** Would a different embedding model retrieve better?

```yaml
active:
  embedding: qwen3-embed-06b     # was nomic-embed
```

Then **restart and fully re-ingest.** Every stored vector came from the old model.

**Expect.** The embedding model defines what "similar" means, so this is
high-leverage for the vector half of hybrid retrieval. It has no effect on BM25.

**Measure.** `end_to_end`. Primary: `recall_at_5`. Secondary: `mrr`, `ndcg_at_10`.

**Read.** A useful diagnostic: turn hybrid search off temporarily (recipe 8) to see
the embedding model's effect in isolation. With hybrid on, BM25 can mask a weaker
embedding model on keyword-heavy questions — fine in production, confusing during
an experiment.

**Caveat.** The most consequential change in the cookbook and the one with the most
ways to go wrong.

A startup check compares your embedding model's dimensions against the vectors
already in ChromaDB and refuses to boot on a mismatch. That saves you from the
obvious error. **It cannot save you from a same-dimension swap** — two models
producing vectors of the same size pass the check and silently give you degraded
retrieval, because you are querying old vectors with a new model's embeddings.
Always re-ingest.

And the privacy interaction: with `pii.enabled: true`, switching to a cloud
embedding provider refuses to boot. Masking covers the generation path, so a cloud
embedder would ship your raw corpus out regardless.

---

## Recipe 7 — Reranker model swap

**Question.** Would a stronger reranker rank better than the default?

```yaml
active:
  reranker: bge-reranker-base     # was minilm-l6
```

Pre-cache before starting, or the startup check fails:

```bash
just init MODEL=BAAI/bge-reranker-base
```

**Expect.** Larger cross-encoders generally rank better and are slower.

| Model | Parameters |
|---|---|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` (default) | 22.7M |
| `BAAI/bge-reranker-base` | 278M |
| `BAAI/bge-reranker-large` | 560M |

Read published comparisons carefully: the BGE rerankers' headline benchmark suite
is predominantly Chinese-language, so those numbers are weak evidence for an
English corpus, and the reported gap between `base` and `large` is small on that
suite. No credible CPU latency figures exist in published sources or in this
repository — which is exactly why you measure it yourself.

**Measure.** `end_to_end`. Primary: `mrr` or `ndcg_at_10`. Secondary:
`latency_p95_ms` — the whole point of the experiment.

**Read.** Quality changes here tend to be small. If your improvement sits inside
the noise floor, the honest conclusion is "no detectable difference," and the
correct action is to keep the faster model.

**Caveat.** The reranker runs on CPU unless a GPU is exposed to the container. On
CPU, the latency difference between a 23M-parameter model and a 560M-parameter one
is not subtle. Measure p95, not the average — reranking cost falls on every query
and shows up in the tail.

---

## Recipe 8 — Hybrid search on or off

**Question.** How much is keyword search actually contributing?

```yaml
retrieval:
  enable_hybrid_search: false
```

**Expect.** A diagnostic more than a tuning knob. Turning hybrid search off drops
you to vector-only retrieval — not by down-weighting BM25, but by routing the query
down a structurally different path that skips BM25 and RRF fusion entirely.

Expect degradation concentrated on questions with rare literal terms: identifiers,
error codes, product names, acronyms. Conceptually phrased questions should barely
move.

**Measure.** `end_to_end`. Primary: `recall_at_5`.

**Read.** The aggregate number matters less than *which questions* changed. If your
corpus is full of technical identifiers and the score barely moves, investigate —
it may mean BM25 is not working rather than that keyword search does not help.

**Caveat — and this one matters. A BM25 failure never fails a query.** If the
`pg_textsearch` extension or the BM25 index is broken, the retriever catches the
error and returns an empty list, so every query quietly degrades to vector-only.

Before concluding "hybrid search doesn't help my corpus," confirm BM25 is running:

```bash
curl -s http://localhost:8001/metrics/system | jq '.component_status.bm25'
# "healthy"     — index works and the last retrieval succeeded
# "unhealthy"   — index works but the last retrieval failed
# "unavailable" — the extension or index cannot be queried at all
```

That endpoint probes the index directly, so it answers even before you run a query.
The logs carry the same information at `ERROR` level:

```bash
docker compose logs rag-server | grep -i bm25
```

A hybrid-on run scoring identically to a hybrid-off run is the exact signature of
BM25 silently returning nothing. Verify before you conclude.

---

## A suggested order

Highest-information experiments first:

1. **Verify BM25 works** (recipe 8) — everything else assumes retrieval is intact.
2. **Reranking on/off** (recipe 1) — largest reliable quality lever, cheap to test.
3. **`top_k` / `top_n`** (recipe 5) — cheap, and diagnoses whether you have a
   finding problem or a ranking problem.
4. **Generation model** (recipe 2) — cheap, and the cost impact is usually large.
5. **Embedding model** (recipe 6) — expensive, high leverage.

Then, if time allows: contextual retrieval (recipe 4, expensive), chunk size
(recipe 3, needs a code change), and the reranker model (recipe 7, usually small
differences — save it for last).

---

**Next:** [8. Privacy and PII](08-privacy-and-pii.md), or
[11. Limits and caveats](11-limits-and-caveats.md).
