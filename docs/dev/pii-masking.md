# PII Masking

Optional feature to anonymize sensitive data before sending to cloud LLM providers. Uses Microsoft Presidio for PII detection and reversible token-based masking.

**Status**: Implemented (`infrastructure/pii/`), opt-in via `pii.enabled`

## How It Works

1. **Masking (outbound)**: PII detected via Microsoft Presidio (NER + regex), replaced with tokens like `[[[PERSON_0]]]`
2. **Token mapping**: Original values stored temporarily (session-scoped)
3. **Unmasking (inbound)**: Tokens in LLM response replaced with original values
4. **Validation**: Detects if LLM altered tokens, attempts fuzzy recovery
5. **Output guardrails**: Scans final response for accidentally leaked PII

## Start With the Provider Contract, Not the Masking

Masking is defense-in-depth. It is a mitigation applied to text that is still
leaving your network, and its ceiling is the detector's recall — which is not
high (see Limitations). The stronger control for a small company costs a form
rather than an engineering quarter:

- **Anthropic API**: commercial/API traffic is excluded from training; retention
  is 7 days (reduced from 30 in Sept 2025). Zero Data Retention agreements are
  available to qualifying enterprise customers.
- **OpenAI API**: API data is not used for training by default; ~30-day abuse
  monitoring retention, waivable via an approved Zero Data Retention plan.

Get ZDR or an equivalent DPA in place first, keep embeddings local (enforced at
boot), then enable masking on top. Do not treat `pii.enabled: true` as the thing
that makes cloud generation safe.

## Configuration

Enable in `config.yml`:

```yaml
pii:
  enabled: true
  allow_cloud_judge: false   # see "Evaluation" below
  entities:
    - PERSON
    - EMAIL_ADDRESS
    - PHONE_NUMBER
    - CREDIT_CARD
    - US_SSN
  token_format: "[[[{entity_type}_{index}]]]"
  score_threshold: 0.5
  spacy_model: en_core_web_md
  gliner:                    # optional higher-recall detector, see below
    enabled: false
  validation:
    enabled: true
    max_retries: 2
  output_guardrails:
    enabled: true
    block_on_detection: false
  session_mapping:
    max_sessions: 500
    ttl_seconds: 3600
  audit:
    enabled: true
    log_level: INFO
```

## Detector Backends

`spacy_model` (default `en_core_web_md`) drives Presidio's NER. It is fast
(~15ms/text) and fine on structured entities, but it is the weakest part of the
stack on names — the entity that matters most in business documents.

Setting `pii.gliner.enabled: true` registers a
[GLiNER](https://huggingface.co/urchade/gliner_multi_pii-v1) recognizer
*alongside* spaCy and the regex recognizers rather than replacing them, so
detections only get added. Requires the optional package:

```bash
uv sync --extra gliner                                          # local dev
docker compose build --build-arg INSTALL_GLINER=true rag-server # docker
```

The config is validated at boot: `pii.gliner.enabled: true` without the package
installed refuses to start, rather than silently falling back to spaCy.

Measured difference on this codebase (`tests/test_pii_gliner.py`):

| Input | spaCy only | + GLiNER |
|-------|-----------|----------|
| `Jane_Doe_severance_2025.pdf` | not masked | `[[[PERSON_0]]].pdf` |
| `Call Maria Gonzalez on 555-241-9987` | name only | name **and** phone |
| `Contact John Smith at john@example.com` | both masked | both masked |

Cost: ~160ms per call versus ~15ms, and a ~200MB model download on first use.
Worth it for PII-heavy corpora; skip it if queries are latency-sensitive and the
corpus is mostly structured identifiers (which the regex recognizers handle
better than any NER model anyway).

## Session Token Mappings

Token mappings hold original PII values in cleartext so `[[[PERSON_0]]]` means
the same person across turns. They live in memory only and are bounded two ways
(`pii.session_mapping`): evicted after `ttl_seconds` idle, and capped at
`max_sessions` with LRU eviction. Deleting a session drops its mapping
immediately.

Losing a mapping is safe — the next turn re-masks from the persisted history and
rebuilds it; only token numbering changes. The cache is process-local, which is
correct for the single uvicorn worker the server runs; adding workers would
require session affinity, since a shared store would mean persisting PII.

## Supported Entity Types

`PERSON`, `EMAIL_ADDRESS`, `PHONE_NUMBER`, `CREDIT_CARD`, `US_SSN`, `IBAN_CODE`, `IP_ADDRESS`, `LOCATION`, `DATE_TIME`, `US_BANK_NUMBER`, `US_DRIVER_LICENSE`, `US_PASSPORT`, `MEDICAL_LICENSE`

## Audit Logging

When `audit.enabled: true`, all masking/unmasking operations are logged:

```json
{"operation": "MASK", "timestamp": "...", "context_id": "session_123", "entities_count": 3, "entity_types": ["PERSON", "EMAIL_ADDRESS"]}
{"operation": "UNMASK", "timestamp": "...", "context_id": "session_123", "tokens_found": 3, "tokens_replaced": 3, "validation_passed": true}
```

## Data Flow Points

| Path | Status | Description |
|------|--------|-------------|
| User queries | Masked | Query text, chat history, retrieved context sent to LLM |
| Chunk metadata | Masked | Free-text metadata values (`file_name`, `path`) are masked before the synthesizer renders nodes with `MetadataMode.LLM`; unmasked again on the source nodes returned to the UI. Structural keys (`document_id`, `chunk_index`, `file_type`, `file_hash`, `file_size_bytes`, `uploaded_at`) pass through untouched |
| Contextual retrieval | Masked | Document name + chunk preview masked before the ingestion LLM call; generated prefix unmasked before local storage/embedding (per-document token mapping) |
| Session titles | Masked | First user message sent for title generation |
| Evaluation | Not masked — **gated** | Judge prompts embed retrieved chunks and answers verbatim. With `pii.enabled`, the eval service refuses to start against a non-local judge unless `pii.allow_cloud_judge: true` |

### Evaluation

The eval path is the one place where masking does not apply, and it ships *more*
corpus content than a normal query: `evals/judges/llm_judge.py` interpolates
retrieved chunks and generated answers straight into the judge prompt.

Rather than mask there (which would distort the very text being judged), the eval
service gates it. With `pii.enabled: true` and a cloud judge provider,
`ModelsConfig.load()` raises at startup. Two ways forward:

- Point the judge at a local provider (`ollama`), or
- Set `pii.allow_cloud_judge: true`, which is the explicit statement that the
  eval dataset holds no real PII (e.g. synthetic questions).

## Limitations

- **Detection recall is the weak link.** Published cross-domain benchmarks put
  Presidio-with-spaCy's PERSON F1 between 0.18 and 0.78 and phone between 0.35
  and 0.54 depending on the corpus; email is the outlier at 0.93+ because the
  regex recognizer, not the NER model, handles it. Names joined by separators
  (`Jane_Doe_severance.pdf`) are not detected at all by spaCy — see the strict
  xfail in `tests/test_pii_metadata.py`, and `pii.gliner.enabled` for the fix.
  No open-source detector currently solves cross-domain PII detection; assume
  leakage and set the provider contract accordingly
- **Pseudonymized, not anonymized**: consistent tokens mean the same person is
  re-identifiable across a conversation by anyone holding the transcript. This is
  a risk reduction, not a compliance guarantee
- **Token preservation**: LLMs may alter tokens (e.g., remove brackets). Validation detects this; fuzzy recovery attempts restoration
- **Performance**: Adds ~20-50ms per request for Presidio analysis (~10x that with GLiNER enabled)
- **Not for embeddings**: Embeddings are generated from original text (stored locally in PostgreSQL)
- **Answer quality**: masking degrades responses to people-centric questions —
  the model reasons over `[[[PERSON_0]]]`, not a name

## When to Enable

- Using cloud LLM providers (OpenAI, Anthropic, Google, etc.), **on top of** a
  ZDR/DPA agreement rather than instead of one
- Documents contain PII that shouldn't leave your infrastructure
- Compliance requirements (GDPR, HIPAA, etc.) — as one control among several

Not needed when using Ollama (local inference) as data never leaves your network.
For genuinely sensitive corpora that is still the right answer.
