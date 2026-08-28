# 3. Configure the RAG pipeline

`config.yml` selects the models and retrieval behaviour. This chapter follows the
pipeline from generation and embeddings through search, reranking, and ingestion.

For every key, see
[`docs/internal/configuration-reference.md`](../internal/configuration-reference.md).

## How changes take effect

The file is bind-mounted and reloads after modification. Do not edit it during an
evaluation: one run could then contain two configurations.

| Change | Required action |
|---|---|
| Most settings | Save `config.yml` |
| Startup-validated setting | Restart the affected service |
| Reranker model | Run `just init MODEL=<hugging-face-id>`, then restart |
| Embedding model | Restart and fully re-ingest |
| Chunk size or overlap | Edit code, rebuild, and fully re-ingest |
| Contextual retrieval | Re-ingest documents to test its effect |

Never query an index built by another embedding model. A dimension mismatch fails
at startup, but a same-dimension model swap can silently return poor results.

API keys belong in Compose secret files, not `config.yml`.

## 1. Choose the generation model

```yaml
active:
  inference: gpt5-mini
```

The inference model writes answers from retrieved context. Compare models on:

- faithfulness and answer correctness;
- abstention on unanswerable questions;
- p95 latency and cost; and
- whether document text may leave your network.

A stronger model cannot recover a passage that retrieval missed. Check retrieval
metrics before upgrading generation.

## 2. Choose the embedding model

```yaml
active:
  embedding: qwen3-embed
```

The embedding model defines similarity for vector search. It can have a large
effect on retrieval, but changing it invalidates all stored vectors. Restart and
re-ingest every document after a change. The checked-in `qwen3-embed` is a
self-hosted TEI service (`Qwen/Qwen3-Embedding-0.6B`, 1024 dimensions) that
runs as the `tei` Compose service — no separate install.

When `pii.enabled` is true, the embedding provider must be local. Startup fails if
you select a cloud embedder because raw chunk text is embedded without masking.

## 3. Configure retrieval

### Hybrid search

```yaml
retrieval:
  enable_hybrid_search: true
```

Hybrid search combines:

- **BM25 keyword search** for exact names, IDs, acronyms, and error codes; and
- **vector search** for semantic matches.

Disabling hybrid search uses vector search only. Before comparing the two modes,
confirm `component_status.bm25` is healthy; BM25 errors degrade silently.

### Candidate count

```yaml
retrieval:
  top_k: 10
```

Each search returns up to `top_k` candidates. A larger value can improve recall
but adds search and reranking work. It does not control how many chunks reach the
generation model; `top_n` does.

### Rank fusion

```yaml
retrieval:
  rrf_k: 60
```

RRF gives a result at rank *r* a contribution of `1 / (rrf_k + r)` from each
search. The default makes rank discounts fairly flat over a ten-result list.
Treat `rrf_k` as an advanced shape parameter, not a first tuning target.

## 4. Configure reranking

```yaml
reranker:
  enabled: true

active:
  reranker: minilm-l6
```

The reranker reads each candidate with the question and reorders the list by
relevance. It usually improves ordering and adds latency to every query.

| Key | Model | Parameters |
|---|---|---:|
| `minilm-l6` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | 22.7M |
| `bge-reranker-base` | `BAAI/bge-reranker-base` | 278M |
| `bge-reranker-large` | `BAAI/bge-reranker-large` | 560M |

The selected model defines `top_n`:

```yaml
models:
  reranker:
    minilm-l6:
      top_n: 5
```

`top_n` is the number of chunks sent to the generation model. If omitted, it is
`max(5, retrieval.top_k // 2)`. Raising it increases prompt size, latency, and
cloud input cost, and may add irrelevant context.

## 5. Configure ingestion

### Chunking

Chunk size and overlap are currently hardcoded to 500 and 50 tokens in
`services/rag_server/core/config.py`. They are high-impact settings but are not in
`config.yml`. Testing them requires a code change, image rebuild, and full
re-ingestion.

Smaller chunks retrieve precisely but can split an answer. Larger chunks preserve
more context but may blur the topic represented by an embedding.

### Contextual retrieval

```yaml
retrieval:
  enable_contextual_retrieval: false
  contextual_concurrency: 8
```

When enabled, an LLM writes a short prefix for each chunk before embedding. This
can make isolated chunks easier to retrieve. It also adds one LLM call per chunk,
so measure ingestion time and cost as well as retrieval quality.

The Settings page can toggle this key, but existing chunks do not change. Re-ingest
before evaluating it.

## 6. Configure prompts

`prompts.system`, `prompts.context`, `prompts.condense`, and
`prompts.contextual_prefix` are editable. The context prompt controls grounding,
abstention, and explicit citation instructions.

If you change the abstention wording, update `eval.abstention_phrases` too. The
evaluator detects abstention by case-insensitive substring matching; changing only
one side changes the score without changing behaviour.

## 7. Configure evaluation

```yaml
active:
  eval: gpt5-2
```

The eval model judges faithfulness, correctness, and relevance. A capable judge is
more expensive; a judge from the same provider family as the generation model may
favour that family. Calibrate a new judge before relying on it.

`active.eval` is the only place the judge is chosen. Both the CLI and the eval API
resolve it from here, and the resolved provider, model and execution boundary are
recorded in the run's metadata, so a saved run says which judge actually scored it.

`eval.citation_scope` controls what counts as a citation:

- `retrieved`: every retrieved chunk counts; this mostly re-measures retrieval.
- `explicit`: the model must emit numbered citations.

`eval.scoring` sets weighted-score objectives and normalization thresholds. Edit
it before an experiment. Runs scored with different weights are not comparable.

## 8. Configure privacy

The strongest supported posture for a confidential corpus is AWS private mode:
customer-managed vLLM inference and judging with local TEI embeddings. Laptop
Compose uses cloud generation; there, `pii.enabled: true` masks detected
identifiers in outbound text. Masking is reversible pseudonymisation, not
anonymisation. See [Chapter 12](12-private-aws-demo.md).

Important keys:

| Key | Effect |
|---|---|
| `pii.entities` | Entity types to detect |
| `pii.score_threshold` | Detection confidence floor |
| `pii.spacy_model` | spaCy model used for name detection |
| `pii.gliner.enabled` | Adds a stronger, slower recognizer |
| `pii.output_guardrails.block_on_detection` | Blocks detected output on non-streaming responses |

Evaluation is governed separately, because nothing on the eval path is masked:
the judge sees retrieved chunks and answers verbatim whatever `pii.enabled` says.

| Key | Effect |
|---|---|
| `models.*.<name>.execution_boundary` | Declares where that endpoint runs: `customer_managed`, `aws_managed`, or `third_party`. Never inferred from the provider name; an endpoint that declares none is refused |
| `data_policy.corpus_confidential` | Whether corpus content needs protecting at all (default `true`) |
| `data_policy.allowed_judge_boundaries` | Allow-list of boundaries a confidential corpus may be judged in (default `customer_managed`, `aws_managed`) |
| `data_policy.public_datasets` | Datasets whose questions and gold passages carry nothing of yours. A run is public only if *every* dataset it uses is listed; `golden` is deliberately absent |
| `data_policy.eval_index_is_isolated` | Set `true` only when an `end_to_end` eval queries an index holding nothing but its own uploaded documents. A public dataset is not sufficient in that tier — the eval queries your live index |

See [Chapter 8](08-privacy-and-pii.md) before enabling cloud processing for
sensitive data.

## Trade-off summary

| Setting | Quality | Query latency | Cloud cost | Re-ingest? |
|---|---|---|---|---|
| Stronger generation model | Often improves | Usually increases | Usually increases | No |
| Different embedding model | Can improve retrieval | Varies | Varies | **Yes** |
| Larger `top_k` | Can improve recall | Increases | Little direct effect | No |
| Larger `top_n` | More context; may dilute | Increases | Increases | No |
| Reranking | Often improves ordering | Increases | No direct cloud cost | No |
| Contextual retrieval | Can improve recall | No query effect | Ingestion cost | **Yes** |
| Different chunking | Corpus-dependent | Varies | Varies | **Yes** |

Cost metrics use hardcoded price tables. Use them to compare runs, not to predict
an invoice. A local model has no API charge but still uses hardware.

## Confirm the active configuration

```bash
just show-config
just show-config-full
```

The full view includes retrieval, reranking, evaluation, and PII settings. Read
`config.yml` directly for database and chat-memory settings.

**Next:** [4. Evaluation concepts](04-evaluation-concepts.md).
