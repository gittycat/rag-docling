# 8. Privacy and PII masking

RAGBench supports two privacy modes:

| Mode | Configuration | Strength |
|---|---|---|
| Keep processing local | Ollama-backed inference and embeddings | Structural: document text is not sent to a model provider |
| Use cloud generation with masking | `pii.enabled: true` and local embeddings | Mitigation: detected identifiers are replaced before cloud calls |

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

The eval service also refuses a cloud judge unless
`pii.allow_cloud_judge: true`. Judge prompts contain unmasked chunks and answers.
Enable this only for evaluation data that contains no real PII.

## What is masked

| Masked before a cloud call | Kept unmasked and local |
|---|---|
| Query and chat history | Embedding input; local embeddings are enforced |
| Retrieved context | Local reranker input |
| Session-title input | Sources returned to the user |
| Contextual-prefix document name and chunk preview | Stored documents, chunks, and chat history |

The generated contextual prefix is unmasked before local storage and embedding.
Masking is a transmission-time control, not storage encryption.

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
