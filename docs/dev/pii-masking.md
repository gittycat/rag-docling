# PII Masking

Optional feature to anonymize sensitive data before sending to cloud LLM providers. Uses Microsoft Presidio for PII detection and reversible token-based masking.

**Status**: Implemented (`infrastructure/pii/`), opt-in via `pii.enabled`

## How It Works

1. **Masking (outbound)**: PII detected via Microsoft Presidio (NER + regex), replaced with tokens like `[[[PERSON_0]]]`
2. **Token mapping**: Original values stored temporarily (session-scoped)
3. **Unmasking (inbound)**: Tokens in LLM response replaced with original values
4. **Validation**: Detects if LLM altered tokens, attempts fuzzy recovery
5. **Output guardrails**: Scans final response for accidentally leaked PII

## Configuration

Enable in `config.yml`:

```yaml
pii:
  enabled: true
  entities:
    - PERSON
    - EMAIL_ADDRESS
    - PHONE_NUMBER
    - CREDIT_CARD
    - US_SSN
  token_format: "[[[{entity_type}_{index}]]]"
  score_threshold: 0.5
  validation:
    enabled: true
    max_retries: 2
  output_guardrails:
    enabled: true
    block_on_detection: false
  audit:
    enabled: true
    log_level: INFO
```

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
| Evaluation | Not masked | Test data sent to evaluation LLM (`services/evals`) — do not point evals at documents containing real PII |

## Limitations

- **Detection recall is the weak link**: the default `en_core_web_md` backend misses a large share of names. Notably, names joined by separators in filenames (`Jane_Doe_severance.pdf`) are **not** detected — spaCy NER needs natural-language context. Masking the metadata plumbing does not fix this; a stronger backend (GLiNER recognizer) or separator normalization does. See the strict xfail in `tests/test_pii_metadata.py`
- **Token preservation**: LLMs may alter tokens (e.g., remove brackets). Validation detects this; fuzzy recovery attempts restoration
- **Performance**: Adds ~20-50ms per request for Presidio analysis
- **Not for embeddings**: Embeddings are generated from original text (stored locally in PostgreSQL)

## When to Enable

- Using cloud LLM providers (OpenAI, Anthropic, Google, etc.)
- Documents contain PII that shouldn't leave your infrastructure
- Compliance requirements (GDPR, HIPAA, etc.)

Not needed when using Ollama (local inference) as data never leaves your network.
