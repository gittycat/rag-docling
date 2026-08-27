# 8. Privacy and PII masking

RAGBench supports two privacy modes:

| Mode | Configuration | Strength |
|---|---|---|
| Keep processing local | Self-hosted `tei` embeddings and a self-hosted `vllm` inference endpoint | Structural: document text is not sent to a model provider |
| Use cloud generation with masking | `pii.enabled: true` and local (`tei`) embeddings | Mitigation: detected identifiers are replaced before cloud calls |

Masking is weaker. Use local processing for genuinely sensitive documents.

## What masking does and does not do

Masking reduces directly identifying information sent in queries, chat history,
retrieved passages, contextual-prefix requests, and session-title requests.

It does not:

- anonymize the document;
- hide surrounding facts that can identify a person;
- protect data at rest;
- guarantee that every identifier is detected; or
- establish legal or regulatory compliance.

The transformation is reversible pseudonymisation. Treat it as defence in depth,
not permission to send sensitive data to a third party.

## Enable masking

```yaml
pii:
  enabled: true
```

Restart the services. Startup refuses two unsafe or incomplete configurations:

| Condition | Reason |
|---|---|
| Cloud embedding provider | Embedding receives raw document text; masking covers the generation path |
| GLiNER enabled but not installed | The requested detector cannot run |

Evaluation has its own, separate refusal that does not depend on `pii.enabled` —
see [Where evaluation data may go](#where-evaluation-data-may-go) below.

## What is masked

| Masked before a cloud call | Kept unmasked and local |
|---|---|
| Query and chat history | Embedding input; local embeddings are enforced |
| Retrieved context | Local reranker input |
| Session-title input | Sources returned to the user |
| Contextual-prefix document name and chunk preview | Stored documents, chunks, and chat history |

The generated contextual prefix is unmasked before local storage and embedding.
Masking is a transmission-time control, not storage encryption.

## Where evaluation data may go

Masking never applies to evaluation. The LLM judge is given retrieved chunks and
generated answers verbatim, so an eval run sends *more* corpus text to the judge
than an ordinary query sends to the generation model. Turning `pii.enabled` on
does not change this.

Because of that, judge egress is controlled by its own `data_policy` block rather
than by the masking settings. Two ideas do the work:

**Execution boundary.** Every model definition under `models.*` declares where
that endpoint actually runs:

| `execution_boundary` | Means |
|---|---|
| `customer_managed` | A host or VPC you run — local Docker, your own EC2 or Kubernetes |
| `aws_managed` | Bedrock or SageMaker: inside your AWS account, but not on your host |
| `third_party` | OpenAI, Anthropic, or any other vendor-hosted API |

The boundary is a property of the endpoint, not of the provider name. The same
OpenAI-compatible protocol can address a container you run or a vendor's API, and
only you know which — so you declare it. A model definition that declares no
boundary is treated as unknown, and unknown is refused.

**Data policy.** `data_policy` states what your corpus tolerates:

```yaml
data_policy:
  corpus_confidential: true          # default: silence is not consent to publish
  allowed_judge_boundaries:          # allow-list; anything absent is refused
    - customer_managed
    - aws_managed
  public_datasets:                   # datasets that carry nothing of yours
    - ragbench
    - qasper
    - squad_v2
    - hotpotqa
    - msmarco
  eval_index_is_isolated: false      # true only for a throwaway eval index
```

The eval service refuses to start a run when the corpus is confidential, this
run's content is not public, and the resolved judge's boundary is not on the
allow-list — including when it declares no boundary at all.

**Publicity is decided per run, from the datasets and the tier — not once for the
whole deployment.** A run is public only when *every* dataset it uses is in
`public_datasets`, and, in the `end_to_end` tier, only when
`eval_index_is_isolated` is also true.

`public_datasets` lists the datasets whose questions and gold passages contain
nothing of yours: the public HuggingFace benchmarks. **`golden` is deliberately
absent** — it is authored from your own documents. Add a dataset to this list only
if that is genuinely true of it.

`eval_index_is_isolated` exists because a public dataset is not enough in the
`end_to_end` tier. There the eval queries your live index and the judge sees
whatever comes back — your documents included — no matter which dataset asked the
question. Set it `true` only when the index the eval runs against holds nothing
but the eval's own uploaded documents. The evals service also honours
`EVAL_INDEX_IS_ISOLATED=true` for ephemeral stacks that cannot edit `config.yml`;
it logs a warning when it does.

### What this changes in practice

Every judge shipped in `models.eval` is `third_party`, so with the shipped
defaults:

| Run | Outcome |
|---|---|
| `just eval --tier generation --datasets squad_v2` | allowed — public dataset, no index queried |
| `just eval --datasets golden` | **refused** — `golden` is your own documents |
| `just test-eval` (ragbench, `end_to_end`) | **refused** — queries the live index |

That last one is a deliberate change. `just test-eval` used to pass because one
global flag said the dataset was public; it never noticed that the tier was
reaching into your corpus. Every refusal names three ways out: point `active.eval`
at an in-boundary judge (`just judge-up` starts one — see
[Chapter 3](03-configuration-tour.md)), declare the index isolated if it really
is, or declare the corpus non-confidential.

Adding `third_party` to `allowed_judge_boundaries` is a fourth way out and a
deliberate statement that your corpus may reach a vendor API — a decision to
record, not a workaround for the check.

## How detection works

Microsoft Presidio combines pattern recognizers with a spaCy named-entity model.
By default it detects:

`PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD`, `US_SSN`, `IBAN_CODE`,
and `IP_ADDRESS`.

Entities scoring at least `pii.score_threshold` are replaced with tokens such as
`[[[PERSON_0]]]`. The token mapping stays in memory per session, with a time-to-live
and session limit. Original values are not written to the audit log at INFO level.

Structured identifiers have recognizable formats. Names do not, so `PERSON`
detection is the weakest area. Test unusual names, non-Western names, names that
are common words, and names inside tables or headings.

### Detection settings

| Setting | Effect |
|---|---|
| `pii.entities` | Selects entity types |
| `pii.score_threshold` | Lower values catch more entities and create more false positives |
| `pii.spacy_model` | Selects the spaCy recognizer model |
| `pii.gliner.enabled` | Adds a second recognizer at much higher CPU cost |

A larger general spaCy model is not necessarily a targeted improvement for names.
Measure detection on representative content instead of assuming model size solves
the problem.

## Guardrails and audit

| Setting | Default | Behaviour |
|---|---:|---|
| `pii.validation.enabled` | `true` | Checks that masking tokens survive model output and attempts fuzzy recovery |
| `pii.output_guardrails.enabled` | `true` | Scans the final unmasked response for PII |
| `pii.output_guardrails.block_on_detection` | `false` | Raises instead of only recording a detection on non-streaming output |
| `pii.audit.enabled` | `true` | Records entity types and counts, not values, at INFO level |

Output guardrails cannot block a streaming response because chunks have already
reached the client before the complete answer can be scanned. Streaming is
audit-only even when `block_on_detection` is true.

## Verify the configuration

1. **Test the startup gate.** Enable PII with a cloud embedding model. Startup
   should fail with a clear error.
2. **Inspect audit events.** Send a query containing a known name and email:

   ```bash
   docker compose logs rag-server | grep -i pii
   ```

3. **Test representative documents.** Include real formatting and the name forms
   used in your corpus.
4. **Inspect misses.** Look for identifiers absent from both tokens and audit
   counts, especially in tables, headers, signatures, and hyphenated names.

No measured residual-leak rate exists for the shipped configuration. Your own
content test is the relevant evidence.

## Measure the cost

Detection runs over the query, history, and retrieved chunks. GLiNER increases CPU
work substantially. Contextual retrieval also invokes masking for every chunk
preview during ingestion.

Masking can reduce answer quality:

- a person’s name becomes an opaque token;
- false positives can remove a needed product or technical term;
- token changes can disrupt references across turns; and
- the model may handle token-shaped text awkwardly.

Measure the effect with the same golden set, first with masking disabled and then
enabled. Compare faithfulness, correctness, abstention, and latency using the
workflow in Chapter 6.

## Operating practices

- Default to local models for sensitive corpora.
- Tune the threshold according to the relative cost of a miss and a false positive.
- Keep an adversarial detection set and rerun it after changing detector settings.
- Review audit counts regularly; an unexpected drop can signal a failure.

**Next:** [9. Read the dashboard](09-reading-the-dashboard.md).

Implementation detail: [`docs/internal/pii-masking.md`](../internal/pii-masking.md).
Presidio documentation: <https://microsoft.github.io/presidio/>
