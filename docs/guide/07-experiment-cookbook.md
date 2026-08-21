# 7. Experiment recipes

Each recipe applies the comparison workflow from Chapter 6. Before any experiment:

1. establish repeat-run noise with `--no-judge-cache`;
2. choose the primary metric and decision rule;
3. change one setting; and
4. keep dataset, sample count, seed, judge, and scoring fixed.

All example scores are illustrative.

## Choose the right tier

| Change | Tier |
|---|---|
| Generation model or prompt | `generation` |
| Reranking, `top_k`, `top_n`, hybrid search | `end_to_end` |
| Embedding model, chunking, contextual retrieval | `end_to_end` |

The `golden` dataset supports only `generation`. Use it for generation changes on
your content. Built-in `end_to_end` datasets test retrieval changes on benchmark
corpora, not on your indexed documents. Extending end-to-end evaluation with your
own corpus is not currently built in.

Use this command pattern:

```bash
just eval --tier <tier> --datasets <dataset> --samples <n> \
  --seed 42 --name "baseline"
# change one setting and confirm it
just show-config-full
just eval --tier <tier> --datasets <dataset> --samples <n> \
  --seed 42 --name "candidate"
just eval-compare <baseline_id> <candidate_id>
```

## Recipe 1 — Is reranking worth it?

Change:

```yaml
reranker:
  enabled: false
```

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Dataset | `ragbench` or another annotated end-to-end dataset |
| Primary metric | `mrr` or `recall_at_5` |
| Guardrails | `faithfulness`, `latency_p95_ms` |

Reranking changes order inside the candidate pool. Expect `mrr`, `ndcg_at_10`,
and `recall_at_5` to move more than `recall_at_10`. If only one ordering metric
moves, the evidence is weak.

Warm the reranker before measuring latency. Its first query after startup includes
a one-time model load.

## Recipe 2 — Local vs cloud generation model

Change:

```yaml
active:
  inference: granite4-8b  # was gpt5-mini
```

| Item | Choice |
|---|---|
| Tier | `generation` |
| Dataset | `golden`; add `squad_v2` for abstention |
| Primary metric | `faithfulness` |
| Guardrails | `answer_correctness`, `abstention_false_negative_rate`, p95 latency, cost |

This experiment tests whether the model follows the context and abstention
instructions. Include unanswerable questions or the abstention rates will be
undefined.

The default judge and cloud generator are both OpenAI models. An LLM judge may
favour its own family. For an important decision, repeat the comparison with an
Anthropic judge and review a sample of answers manually.

Local latency depends on your hardware. The cost metric records Ollama API cost as
zero but does not include hardware.

## Recipe 3 — Chunk size

Chunk size and overlap are hardcoded:

```python
Settings.chunk_size = 500
Settings.chunk_overlap = 50
```

Change them in `services/rag_server/core/config.py`, rebuild, and re-ingest:

```bash
just build
just up
```

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Dataset | An annotated end-to-end dataset |
| Primary metric | `recall_at_5` |
| Guardrails | `precision_at_5`, `faithfulness`, ingestion time |

Larger chunks preserve surrounding context but make embeddings less specific.
Smaller chunks match more precisely but can split an answer across chunks. Test
size and overlap separately; both require a rebuild and re-ingestion.

This experiment reports benchmark-corpus behaviour because custom end-to-end
evaluation is not built in.

## Recipe 4 — Contextual retrieval on or off

Change:

```yaml
retrieval:
  enable_contextual_retrieval: true
```

Re-ingest after each change. The setting affects stored chunk embeddings, not only
future queries.

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Dataset | An annotated end-to-end dataset |
| Primary metric | `recall_at_5` |
| Guardrails | `mrr`, faithfulness, ingestion duration and cost |

Contextual retrieval adds an LLM-written description to each chunk. It is most
useful when chunks are ambiguous outside their document. It also adds one LLM call
per chunk, so ingestion cost may decide the experiment even when retrieval
improves.

`retrieval.contextual_concurrency` defaults to 8. Raising it may shorten ingestion
if the provider accepts the parallel calls. Anthropic’s published method is useful
background, but its benchmark is not a prediction for your corpus:
[Introducing Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval).

## Recipe 5 — `top_k` and `top_n`

Test the settings separately:

```yaml
retrieval:
  top_k: 20

models:
  reranker:
    minilm-l6:
      top_n: 5
```

| Setting | Raising it does | Main cost |
|---|---|---|
| `top_k` | Expands the candidate pool | Search and reranking time |
| `top_n` | Sends more chunks to generation | Prompt tokens, latency, possible distraction |

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Primary metric | `recall_at_5` |
| Guardrails | `precision_at_5`, faithfulness, p95 latency, cost |

First compare baseline `recall_at_10` with `recall_at_5`:

- a large gap means the right passage is found but ranked too low;
- both low means the candidate pool often misses the passage.

Hold `top_n` fixed while changing `top_k`, then hold the chosen `top_k` fixed while
changing `top_n`. If cost stays flat after a larger prompt, confirm the provider
returned token usage.

## Recipe 6 — Embedding model swap

Change:

```yaml
active:
  embedding: qwen3-embed-06b  # was nomic-embed
```

Restart and fully re-ingest. Do this even if both models use the same vector
dimension; the startup check cannot detect same-dimension incompatibility.

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Primary metric | `recall_at_5` |
| Guardrails | `mrr`, `ndcg_at_10`, ingestion time |

Hybrid search can hide vector-search differences when BM25 finds the answer. For a
diagnostic run, compare embedding models with hybrid search disabled, then confirm
the chosen model with production settings restored.

PII masking requires a local embedding provider. Selecting a cloud embedder while
`pii.enabled` is true fails at startup.

## Recipe 7 — Reranker model swap

Change and pre-cache the model:

```yaml
active:
  reranker: bge-reranker-base
```

```bash
just init MODEL=BAAI/bge-reranker-base
```

| Model | Parameters |
|---|---:|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 22.7M |
| `BAAI/bge-reranker-base` | 278M |
| `BAAI/bge-reranker-large` | 560M |

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Primary metric | `mrr` or `ndcg_at_10` |
| Guardrail | `latency_p95_ms` |

Larger models may rank better and are slower, especially on CPU. If a quality gain
falls within repeat-run noise, keep the faster model. Exclude the first, cold
query from latency comparisons.

## Recipe 8 — Hybrid search on or off

Change:

```yaml
retrieval:
  enable_hybrid_search: false
```

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Primary metric | `recall_at_5` |
| Diagnostic | Review questions containing identifiers, acronyms, and exact names |

Turning hybrid search off selects vector-only retrieval and skips BM25 and RRF.
The aggregate difference matters less than which questions change.

Before testing, confirm BM25 is healthy:

```bash
curl -s http://localhost:8001/metrics/system \
  | jq '.component_status.bm25'
docker compose logs rag-server | grep -i bm25
```

A BM25 error does not fail the query; it silently returns no keyword results. If
hybrid-on and hybrid-off runs are identical, verify BM25 before concluding that
keyword search adds no value.

## Suggested order

1. Verify BM25 and test hybrid search.
2. Test reranking on and off.
3. Tune `top_k`, then `top_n`.
4. Compare generation models.
5. Compare embedding models.
6. Test contextual retrieval, chunking, and larger rerankers only when the earlier
   results justify their extra setup or cost.

**Next:** [8. Privacy and PII](08-privacy-and-pii.md), or review
[11. Limits and caveats](11-limits-and-caveats.md) before sharing results.
