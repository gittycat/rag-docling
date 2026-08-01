# 7. Experiment cookbook

Eight concrete experiments, each in the same shape: the question, what to change,
what to expect, how to measure, how to read the result, and the caveat that will
otherwise catch you out.

All of them assume the discipline from [chapter 6](06-tuning-workflow.md):
establish a noise floor first by running your baseline twice, choose your primary
metric before you look at results, and keep your own record of what each run
actually ran — because the saved config snapshot does not reliably capture
`retrieval_top_k`, `hybrid_search_enabled`, or `contextual_retrieval_enabled`.

**Any numbers shown below are illustrative.** This system ships with no measured
before/after results, and none are invented here.

---

## Choosing your tier

Get this wrong and you measure nothing. The rule:

> If what you changed happens **before** the model sees its context, you need
> `end_to_end`. If it happens **after**, `generation` gives a cleaner signal.

| Experiment | Tier | Why |
|---|---|---|
| Reranking on/off | `end_to_end` | Reranking is in the retrieval path |
| Reranker model swap | `end_to_end` | Same |
| `top_k` | `end_to_end` | Same |
| Hybrid search on/off | `end_to_end` | Same |
| Embedding model | `end_to_end` | Retrieval only |
| Chunk size | `end_to_end` | Ingestion-time |
| Contextual retrieval | `end_to_end` | Ingestion-time |
| Generation model | either | `generation` isolates it; `end_to_end` shows the whole system |

The `generation` tier bypasses retrieval completely — passages are handed to the
model directly. Testing a retrieval change there measures nothing whatsoever, and
it will not error; it will just report numbers that did not move.

This also means **your golden set cannot test retrieval changes.** The golden
dataset supports only the `generation` tier, and populates no gold passages. For
retrieval experiments use `ragbench`, `hotpotqa`, or `msmarco` in `end_to_end`,
and accept that you are measuring on someone else's documents.

---

## Recipe 1 — Is reranking worth it?

**The question.** Reranking adds latency to every query. Does the quality justify
it on my corpus?

**What to change.**

```yaml
reranker:
  enabled: false
```

**What to expect.** Reranking is the most reliable quality lever in the retrieval
stage. It re-scores candidates by reading each one against the question, rather
than inferring relevance from rank position as fusion does. Turning it off should
degrade ordering-sensitive metrics and cut latency.

**How to measure.**

```bash
just eval --tier end_to_end --datasets ragbench --samples 50 \
  --seed 42 --name "rerank-on"
# edit config.yml, confirm with: just show-config-full
just eval --tier end_to_end --datasets ragbench --samples 50 \
  --seed 42 --name "rerank-off"
just eval-compare <run_a> <run_b>
```

Primary metric: `recall_at_5` or `mrr` — reranking changes *ordering*, and these
are the ordering metrics. Secondary: `faithfulness`, `latency_p95_ms`.

**How to read it.** Look for the coherent pattern. Real reranking value shows up
as `mrr`, `ndcg_at_10`, and `recall_at_5` all moving together, with
`faithfulness` following because better-ordered context produces better-grounded
answers. `recall_at_10` should move *less* than `recall_at_5` — reranking
reorders within the candidate pool rather than expanding it, so it should mostly
affect the top of the list.

If only one of those metrics moved, treat it as noise.

**Caveat.** The reranker is loaded lazily on first use and cached for the process
lifetime, so the very first query after a restart includes a one-time model load.
Do not include a cold first query in a latency comparison. Also note the reranker's
output size is `max(5, top_k / 2)` — with the default `top_k` of 10, reranking
narrows 10 candidates to 5. If `top_k` is large, reranking is doing much more
filtering, and its impact will be correspondingly larger.

---

## Recipe 2 — Local vs cloud generation model

**The question.** A local model is free and private. What does it cost me in
quality?

**What to change.**

```yaml
active:
  inference: gemma3-4b     # was gpt5-mini
```

**What to expect.** The gap usually shows up in instruction-following rather than
raw knowledge — which matters here, because RAG's whole premise is that the model
reads the provided context rather than recalling. Watch specifically for the model
ignoring the "answer only from the context" instruction, and for the abstention
behaviour degrading.

**How to measure.** Use the `generation` tier to isolate the model from retrieval
variance:

```bash
just eval --tier generation --datasets golden --samples 40 \
  --seed 42 --name "cloud-gen"
just eval --tier generation --datasets golden --samples 40 \
  --seed 42 --name "local-gen"
```

Primary: `faithfulness`. Secondary: `answer_correctness`,
`abstention_false_negative_rate`, `latency_p95_ms`, `cost_per_query`.

**How to read it.** `abstention_false_negative_rate` is the one to watch most
carefully and the one most people ignore. It measures how often the model answered
a question it should have refused — that is, made something up. A smaller model
that scores slightly worse on correctness but much worse on false negatives is a
substantially riskier system than the correctness number alone suggests.

For abstention to be measurable at all, your dataset needs unanswerable questions.
Add some to your golden set with `"query_type": "unanswerable"`, or use
`squad_v2`, which is built for this.

**Caveat.** This is the experiment where judge bias bites hardest. The shipped
judge is an OpenAI model. Research on LLM-as-judge documents that judges score
outputs from their own model family more favourably, even when generator and
judge are not the identical model. Comparing an OpenAI generator against a local
one using an OpenAI judge is **not a neutral comparison** and is likely to flatter
the cloud model. If this experiment matters to you, set `active.eval` to a judge
from a different vendor — an Anthropic model, say — and see whether the conclusion
survives.

Also: local model latency depends entirely on your hardware, and cost reporting
uses hardcoded rate tables that treat Ollama models as free — true for marginal
cost, silent about the hardware you bought.

---

## Recipe 3 — Chunk size

**The question.** Are 500-token chunks right for my documents?

**What to change.** **This one requires a code edit.** `chunk_size` and
`chunk_overlap` are not in `config.yml`; they are hardcoded in
`services/rag_server/core/config.py`:

```python
chunk_size = 500
chunk_overlap = 50
```

Change them, rebuild the image, **and fully re-ingest your corpus** — existing
chunks were produced by the old settings.

```bash
just build && just up
```

That expense is the main reason to think carefully before running this one. It is
also recorded in [`docs/suggestions.md`](../suggestions.md) as a config key that
should exist.

**What to expect.** The trade-off is coverage against precision. Larger chunks
carry more surrounding context, so a retrieved chunk is more likely to contain the
complete answer — but the embedding averages over more content, blurring what the
chunk is "about" and making it harder to match precisely. Smaller chunks match
precisely and fragment answers across several chunks, so the model may receive
only part of what it needed.

Published work on this varies by corpus and task. One controlled study found 512
tokens optimal in its setup — close to the shipped 500 — but that is one paper's
benchmark on its own data, not a general law. Your documents may differ,
particularly if they are unusually structured: dense reference tables and long
discursive prose do not want the same chunk size.

**How to measure.** `end_to_end` tier, retrieval metrics primary:

```bash
just eval --tier end_to_end --datasets ragbench --samples 50 --seed 42 --name "chunk-500"
# code edit, rebuild, re-ingest
just eval --tier end_to_end --datasets ragbench --samples 50 --seed 42 --name "chunk-250"
```

Primary: `recall_at_5`. Secondary: `precision_at_5`, `faithfulness`.

**How to read it.** Expect recall and precision to move in opposite directions —
that is the trade-off working as described. `faithfulness` is the tiebreaker,
since it reflects whether the model actually had what it needed.

**Caveat.** Overlap is more contested than it looks. The common assumption is that
overlap preserves context across boundaries, but at least one controlled study
found overlap provided **no measurable benefit** while increasing indexing cost.
Sources genuinely disagree. If you are already paying to re-ingest, testing
`chunk_overlap = 0` costs you nothing extra and may be informative.

There is also **no reliable general guidance on how chunk size and reranker
settings should co-vary** — this is unresolved in the literature, not merely
undocumented here. Vary one at a time.

---

## Recipe 4 — Contextual retrieval on or off

**The question.** Is one LLM call per chunk at ingestion worth what it buys?

**What to change.**

```yaml
retrieval:
  enable_contextual_retrieval: true
```

This is the one key the running application can change — the settings page toggles
it. Either way, **you must re-ingest**: the setting affects how chunks are built.

**What to expect.** Each chunk gets a one-to-two sentence generated description of
what it is and where it came from, prepended before embedding. The intent is to
rescue chunks that are meaningless in isolation — a paragraph beginning "this
approach was rejected for the reasons above" is nearly unretrievable on its own.

Anthropic's published results for this technique are the reference point, and they
need reading carefully. On their benchmark, combining contextual embeddings with
contextual BM25 reduced top-20 retrieval failures by **49%** (5.7% → 2.9%).
Contextual embeddings *alone* achieved 35%. Adding reranking on top reached 67%.

Two things follow. The 49% figure **already assumes hybrid search** — it is not an
additional gain layered on top of a separate hybrid-search benefit. And RAGBench
ships with reranking enabled by default, so the configuration you are actually
running corresponds to Anthropic's 67% row, not the 49% one.

Those are Anthropic's numbers on Anthropic's corpus. They are a reason to run the
experiment, not a prediction of your result.
Source: [Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval).

**How to measure.** `end_to_end`, retrieval metrics primary. Also record how long
ingestion took, and what it cost.

**How to read it.** The cost side is what decides this. One LLM call per chunk
means a 10,000-chunk corpus costs 10,000 calls, and re-ingesting for any reason
costs them again. A small retrieval improvement may not be worth that, especially
against a paid API. If retrieval is already strong on your corpus, the headroom
this technique targets may simply not exist.

**Caveat.** Contextual retrieval dominates ingestion time. The claim that it
accounts for roughly 85% of processing time is repeated in this repository's own
notes and **has never been measured** — the only real benchmark in the repo ran
with the feature disabled. Treat it as architecturally plausible and unverified.
Measure your own ingestion time before and after.

Two more: raise `retrieval.contextual_concurrency` (default 8) to speed ingestion
if your provider tolerates the parallelism. And if PII masking is enabled, chunk
previews are masked before this call, which adds detection cost per chunk.

---

## Recipe 5 — `top_k`

**The question.** Should I retrieve more chunks, or fewer?

**What to change.**

```yaml
retrieval:
  top_k: 20    # was 10
```

**What to expect.** More candidates means retrieval has more chances to include
the right passage. It also means a longer prompt on every query, which costs
latency and tokens, and a greater chance that marginally relevant context dilutes
the answer.

Note the coupling from chapter 3: `top_k` also determines how many chunks reach
the model, via `max(5, top_k / 2)`. Going from 10 to 20 takes the model's context
from 5 chunks to 10. You are changing two things at once and cannot separate them
— note that in your record.

**How to measure.** `end_to_end`. Primary: `recall_at_5`. Secondary:
`precision_at_5`, `faithfulness`, `latency_p95_ms`, `cost_per_query`.

**How to read it.** Compare `recall_at_10` against `recall_at_5` in your baseline
first. **If `recall_at_10` is much higher than `recall_at_5`, the right passage is
being found but ranked too low** — that is a reranking problem, and raising
`top_k` alone will not fix it. If both are similarly low, retrieval is not finding
the passage at all, and a larger pool may genuinely help.

**Caveat.** `cost_per_query` scales roughly with prompt length, so doubling
`top_k` should visibly raise it. If it does not, check whether your provider is
reporting token counts at all — token usage is omitted when the provider does not
report it, which makes cost look flat when it is not.

---

## Recipe 6 — Embedding model swap

**The question.** Would a different embedding model retrieve better?

**What to change.**

```yaml
active:
  embedding: openai-3-small     # was nomic-embed
```

Then **restart and fully re-ingest.** Every stored vector came from the old model
and is not comparable to queries embedded by the new one.

**What to expect.** The embedding model defines what "similar" means, so this is
high-leverage for the vector half of hybrid retrieval. It has no effect on BM25.

**How to measure.** `end_to_end`. Primary: `recall_at_5`. Secondary: `mrr`,
`ndcg_at_10`.

**How to read it.** A useful diagnostic: turn hybrid search off temporarily
(recipe 8) to see the embedding model's effect in isolation. With hybrid search
on, BM25 can mask a weaker embedding model on keyword-heavy questions — which is
fine in production and confusing during an experiment.

**Caveat.** This is the most consequential change in the cookbook and the one with
the most ways to go wrong.

There is a startup check comparing your embedding model's dimensions against the
vectors already in ChromaDB, which will refuse to boot on a mismatch. That check
saves you from the obvious error. **It cannot save you from a same-dimension
swap** — two different models producing vectors of the same size will pass the
check and silently give you degraded retrieval, because you are querying old
vectors with a new model's embeddings. Always re-ingest.

And the privacy interaction: if `pii.enabled` is true, switching to a cloud
embedding provider will refuse to boot. That is deliberate — masking covers the
generation path, so a cloud embedder would ship your raw corpus out regardless.

---

## Recipe 7 — Reranker model swap

**The question.** Would a stronger reranker rank better than the default?

**What to change.**

```yaml
active:
  reranker: bge-reranker-base     # was minilm-l6
```

Pre-cache the model before starting, or the startup check will fail:

```bash
just init BAAI/bge-reranker-base
```

**What to expect.** The default `ms-marco-MiniLM-L-6-v2` is small — roughly 23
million parameters. `bge-reranker-base` and `bge-reranker-large` are substantially
larger (on the order of 278M and 435M). Larger cross-encoders generally rank
better and are slower.

Be careful reading the published comparisons: the BGE rerankers' headline
benchmark suite is predominantly Chinese-language, so those numbers are weak
evidence for an English corpus. The reported gap between `base` and `large` is
small on that suite. No credible CPU latency figures for these models were found
in published sources, and none exist in this repository — which is precisely why
you measure it yourself.

**How to measure.** `end_to_end`. Primary: `mrr` or `ndcg_at_10`. Secondary:
`latency_p95_ms` — this is the whole point of the experiment.

**How to read it.** Quality changes here tend to be small. If your improvement is
within the noise floor you measured in chapter 6, the honest conclusion is "no
detectable difference," and the correct action is to keep the faster model.

**Caveat.** The reranker runs on CPU unless a GPU is exposed to the container. On
CPU, the latency difference between a 23M-parameter model and a 435M-parameter one
is not subtle. Measure p95, not the average — reranking cost falls on every query
and shows up in the tail.

---

## Recipe 8 — Hybrid search on or off

**The question.** How much is keyword search actually contributing?

**What to change.**

```yaml
retrieval:
  enable_hybrid_search: false
```

**What to expect.** This is a diagnostic more than a tuning knob. Turning hybrid
search off drops you to vector-only retrieval — and not by down-weighting BM25,
but by routing the query down a structurally different code path that skips BM25
and RRF fusion entirely.

Expect degradation concentrated on questions containing rare literal terms:
identifiers, error codes, product names, acronyms. Questions phrased
conceptually should barely move.

**How to measure.** `end_to_end`. Primary: `recall_at_5`.

**How to read it.** The aggregate number is less interesting than *which
questions* changed. If your corpus is full of technical identifiers and the score
barely moves, that is worth investigating — it may mean BM25 is not working
properly rather than that keyword search does not help.

Which leads to the important part.

**Caveat — and this one matters.** **BM25 failures are silent.** If the
`pg_textsearch` extension or the BM25 index is broken, the retriever catches the
error, logs a warning, and returns an empty list. Every query then degrades to
vector-only with no error surfaced to you.

So before concluding "hybrid search doesn't help my corpus," confirm BM25 is
actually running:

```bash
docker compose logs rag-server | grep -i bm25
```

A hybrid-on run that scores identically to a hybrid-off run is the exact signature
of BM25 silently returning nothing. Verify before you conclude.

---

## A suggested order

If you are starting from defaults and have limited time, this sequence puts the
highest-information experiments first:

1. **Verify BM25 works** (recipe 8) — everything else assumes retrieval is intact.
2. **Reranking on/off** (recipe 1) — largest reliable quality lever, cheap to test.
3. **`top_k`** (recipe 5) — cheap, and diagnoses whether you have a finding
   problem or a ranking problem.
4. **Generation model** (recipe 2) — cheap, and the cost impact is usually large.
5. **Embedding model** (recipe 6) — expensive, high leverage.
6. **Contextual retrieval** (recipe 4) — expensive, and the cost may dominate the
   decision.
7. **Chunk size** (recipe 3) — expensive, requires a code change.
8. **Reranker model** (recipe 7) — usually small differences; save it for last.

---

**Next:** [8. Privacy and PII](08-privacy-and-pii.md), or
[11. Limits and caveats](11-limits-and-caveats.md) for what these experiments
cannot establish.
