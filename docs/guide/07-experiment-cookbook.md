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

## Recipe 2 — AWS private vs cloud generation

Use [Chapter 12](12-private-aws-demo.md) to start AWS private mode, which
configures the demo instance with the private inference and judge endpoints.
For each mode, select the appropriate active inference model on the environment
being tested and keep the same corpus, prompt, retrieval settings, and judge.

| Item | Choice |
|---|---|
| Tier | `generation` |
| Dataset | `golden`; add `squad_v2` for abstention |
| Primary metric | `faithfulness` |
| Guardrails | `answer_correctness`, `abstention_false_negative_rate`, p95 latency, cost |

This experiment tests whether the model follows the context and abstention
instructions. Include unanswerable questions or the abstention rates will be
undefined.

An LLM judge may favour its own family. For an important decision, review a
sample of answers manually. Supply measured AWS rates using `just llm-price`;
the resulting `MODEL_PRICE_OVERRIDES` includes instance time rather than treating
private vLLM as free.

## Recipe 3 — Chunk size

Change chunk size and overlap in `config.yml`:

```yaml
chunking:
  chunk_size: 500
  chunk_overlap: 50
```

Or set them at runtime without touching `config.yml`:

```bash
curl -X PATCH http://localhost:8001/settings \
  -H 'Content-Type: application/json' \
  -d '{"chunk_size": 800, "chunk_overlap": 80}'
```

No rebuild is needed either way. The new values apply only to documents
ingested after the change, so re-ingest to test them:

```bash
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

A dedicated command runs this whole comparison for you:

```bash
docker compose exec evals .venv/bin/python -m evals.cli contextual-ab \
  --datasets golden --samples 40
```

It ingests the dataset's documents twice — once with contextual retrieval on,
once off — against the RAG server it points at (`--rag-url`, default
`localhost:8001`), restores whatever the setting was before it started (even if
a run fails), and prints the retrieval metric deltas alongside ingestion cost
and latency per document, plus significance. It always runs at `end_to_end`,
since ingestion is what's being compared, and defaults to the `golden` dataset.

Because it flips the live `contextual_retrieval_enabled` setting on the server
and ingests documents into whatever index that server is using, point
`--rag-url` at a disposable or eval-only instance if you don't want the
comparison mixed into a shared index.

To do it by hand instead, change:

```yaml
retrieval:
  enable_contextual_retrieval: true
```

and re-ingest after each change — the setting affects stored chunk embeddings,
not only future queries.

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Dataset | An annotated end-to-end dataset |
| Primary metric | `recall_at_5` |
| Guardrails | `mrr`, faithfulness, `ingestion_cost_per_document`, `ingestion_latency_per_document_ms` |

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

The checked-in baseline (`qwen3-embed` — self-hosted TEI serving
`Qwen/Qwen3-Embedding-0.6B` at 1024 dimensions) itself replaced an
Ollama-served `nomic-embed-text` baseline (768 dimensions). This recipe is both
how that kind of change should be validated and the template for the next one:
add a second `models.embedding` entry in `config.yml`, then change:

```yaml
active:
  embedding: your-new-embedding-alias  # was qwen3-embed
```

Restart and fully re-ingest. Do this even if both models use the same vector
dimension; the startup check cannot detect same-dimension incompatibility —
and if the dimension *does* differ, `vector_store.dimension` and the
`document_chunks.embedding` column type must change too (see
[2. Getting running](02-getting-running.md)), which forces a `docker compose
down -v` and a full re-ingest regardless.

| Item | Choice |
|---|---|
| Tier | `end_to_end` |
| Primary metric | `recall_at_5` |
| Guardrails | `mrr`, `ndcg_at_10`, ingestion time |

**Run the diagnostic with hybrid search disabled**
(`retrieval.enable_hybrid_search: false` — see Recipe 8). Hybrid search's BM25
leg can mask vector-search differences whenever the keyword match alone
already finds the answer, which is exactly the class of case an embedding
swap is meant to move. Confirm the chosen model with production (hybrid-on)
settings restored afterward.

PII masking requires a local embedding provider — `LOCAL_EMBEDDING_PROVIDERS`
currently allows `tei` only. Selecting a cloud embedder while `pii.enabled` is
true fails at startup.

`qwen3-embed`'s `query_instruction` (Qwen3's documented asymmetric query
prefix, applied only to queries via the `tei` provider's `query_instruction` /
`text_instruction` config in `config.yml`) is a candidate for the same kind of
test: whether it measurably improves retrieval over an unprefixed baseline is
not established. An informal A/B run during the TEI migration was
inconclusive — the hand-built ranking set was too easy to discriminate between
the two. A real `end_to_end` run against this recipe's guardrails, with the
prefix toggled via `text_instruction/query_instruction` in `config.yml`, is
what would actually measure it.

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
