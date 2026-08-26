# PII masking

## Threat model and what the tier is for

The PII tier exists for one specific scenario: sending user queries, chat history,
and retrieved document context to a **cloud** LLM provider (OpenAI, Anthropic,
Google, DeepSeek, Moonshot) while limiting how much real personal data leaves the
network in that outbound text. It is opt-in (`pii.enabled: false` by default) and
implemented as reversible tokenization: Presidio detects entities, each detected
value is replaced with a stable token before the request goes out, and the tokens
are swapped back for the originals once the response comes back.

Be precise about what this buys: it is **pseudonymisation, not anonymisation**, and
it is **not a compliance guarantee**. The same token always maps to the same
original value within a session, so anyone holding a transcript (the cloud
provider, a log, a subpoena) can re-identify a person by correlating tokens across
turns and other context in the document — nothing about the masking removes the
identifying signal, it only substitutes it for the outbound wire. Treat this as
defense-in-depth layered on top of a provider contract (Zero Data Retention or
equivalent DPA with the LLM vendor), not as a replacement for one. Detector recall
is also inherently imperfect — no open-source NER stack solves cross-domain PII
detection — so the honest assumption is that some leakage gets through regardless
of configuration.

## Where masking applies, and what is never masked

Masking runs on every path that sends text to the configured (possibly cloud) LLM:

- **Query and chat generation**: the user's query and chat history are masked
  before being sent to the LLM. Retrieved chunk text and its free-text metadata
  values are masked as a node postprocessor step that runs **after reranking** —
  reranking needs the original, unmasked text to score relevance well, so masking
  has to be the last step before prompt assembly. Structural metadata
  (`document_id`, `chunk_index`, `file_type`, `file_hash`, `file_size_bytes`,
  `uploaded_at`) is never masked — these are machine-generated values, not free
  text, and `document_id` in particular must survive verbatim because source
  deduplication keys on it.
- **Contextual retrieval / ingestion**: the document name and a chunk preview are
  masked before being sent to the LLM that generates a contextual prefix for the
  chunk. The generated prefix is then unmasked before it is embedded and stored —
  since the prefix is persisted, and the embedding pipeline (below) never sees
  masked text.
- **Session titles**: the first user message sent for title generation is masked
  under the same policy as the rest of the query path.
- **Responses**: unmasked before being returned to the user. For non-streaming
  responses this is a simple string-replace pass. For streaming responses,
  unmasking is done on a sentence-buffered basis rather than per-token — a token
  like `[[[PERSON_0]]]` could otherwise be split across two SSE events and become
  unrecoverable.

**Never masked, by explicit product decision**: the embeddings path and the
reranker. Both are required to stay local/VM-side, and this is enforced as a hard
boot-time invariant, not a convention — `pii.enabled: true` is rejected at
config-load time if the embedding provider is not in the local-provider set
(currently just `tei`). The reasoning is that embeddings and reranking need the
real text to produce useful vectors and relevance scores, and since both stay
local by construction, masking them would only cost quality for no privacy
benefit — the point of masking is to protect text going to a *remote* LLM, and
local components never send anything off-box.

## Detection engines

**Presidio** (`presidio-analyzer` / `presidio-anonymizer`) is the primary engine —
an `AnalyzerEngine` for detection paired with an `AnonymizerEngine` using a custom
operator for reversible tokenization. Presidio's NLP backend is **spaCy**, model
`en_core_web_md` by default. A larger model, `en_core_web_lg`, is noted in config
as more accurate but roughly 15x larger on disk, and is not the default trade-off.

Default entity types (`pii.entities`, seven enabled out of Presidio's larger
catalogue):

| Entity | Detection source |
|---|---|
| PERSON | spaCy NER (+ GLiNER if enabled) |
| EMAIL_ADDRESS | Presidio pattern recognizer |
| PHONE_NUMBER | Presidio pattern recognizer |
| CREDIT_CARD | Presidio pattern recognizer |
| US_SSN | Presidio pattern recognizer |
| IBAN_CODE | Presidio pattern recognizer |
| IP_ADDRESS | Presidio pattern recognizer |

The full Presidio entity catalogue is larger than this; the enabled list is fully
configurable via `pii.entities`.

Detection confidence threshold: `pii.score_threshold` defaults to `0.5`, applied
identically both when masking outbound text and when scanning the final response
for leaked PII (the output guardrail, below).

## GLiNER: optional additional recognizer, off by default

GLiNER (`urchade/gliner_multi_pii-v1`) can be registered as an **additional**
recognizer alongside spaCy and the regex recognizers — it never replaces them, it
only adds detections spaCy misses. It is off by default
(`pii.gliner.enabled: false`) and requires either a local `uv sync --extra gliner`
or the image built with `--build-arg INSTALL_GLINER=true`. If `pii.gliner.enabled`
is set but the package isn't importable, the server refuses to boot rather than
silently falling back to spaCy-only detection.

GLiNER is meaningfully better on names that spaCy misses entirely — separator-
joined names in filenames (`Jane_Doe_severance_2025.pdf`) are a documented example
that spaCy alone does not catch. GLiNER's own entity mapping also references
Presidio types not in the default `entities` list (`US_PASSPORT`,
`US_DRIVER_LICENSE`, `US_BANK_NUMBER`, `LOCATION`) — those mappings are inert
unless an operator also adds the corresponding type to `pii.entities`.

The only quantified performance figure anywhere in this codebase for GLiNER is a
comment in the config module stating **~160ms per call versus ~15ms** for the
default spaCy path. This is the project's own stated estimate in a code comment,
not an independently measured benchmark — there is no benchmark script or test
that times this in the repo. Treat the ~10x figure as the reason GLiNER ships
opt-in, not as a verified number.

## Token format and reversibility

Tokens use the format `"[[[{entity_type}_{index}]]]"`, e.g. `[[[PERSON_0]]]`. The
same original value always maps to the same token within a session's mapping.
Unmasking does a literal string-replace pass over the token map and reports how
many tokens were found, replaced, and left missing.

The token mapping — a plain `{entity_type: {original: token}}` structure — is kept
**in-memory only, per session, and is never persisted to disk**. This is the
mechanism that makes reversibility possible at all: the server needs the original
values to unmask the response, and deliberately never writes them anywhere durable.
The mapping cache is bounded two ways: an idle TTL (`pii.session_mapping.ttl_seconds`,
default 3600s) and an LRU cap (`pii.session_mapping.max_sessions`, default 500).
Losing a mapping is safe by design — the next turn re-masks from the persisted
chat history and rebuilds the mapping; only the token numbering changes, nothing is
silently unmasked. The cache is explicitly process-local, which is correct for the
single uvicorn worker the server runs today — a multi-worker deployment would need
session affinity, or would force persisting PII to share state, which the design
rejects.

## Validation and fuzzy recovery

After unmasking, the service validates that all expected tokens were actually
replaced. LLMs sometimes mangle tokens in the response (dropping brackets,
changing case, swapping separators), so a fuzzy-recovery pass tries several common
variants — brackets stripped, single-bracket, underscore-to-space,
underscore-to-hyphen, lowercased, uppercased — before falling back to reporting the
token as missing.

`pii.validation.max_retries` (default 2) and `pii.validation.alert_on_failure`
(default `true`) are parsed into config, and read as if they govern a retry loop
and an alerting path for validation failures. **They are not acted on anywhere in
the code.** Validation runs once per response; there is no retry loop that
re-queries the LLM on a validation failure, and no alerting mechanism fires when
`alert_on_failure` would apply. These are dead configuration today — present in
`config.yml`, parsed into the config object, and otherwise inert.

## Output guardrails

A separate scan runs on the **final, unmasked** response text to catch PII the LLM
may have invented or leaked verbatim rather than echoed via a token — this is a
different check from token validation above. It uses the same detection engines
and `score_threshold`. By default (`pii.output_guardrails.block_on_detection:
false`) a detection is only logged, not blocked. Setting `block_on_detection: true`
makes a detected leak raise an error instead of returning the response.

**Why the streaming path can only audit, not block**: for non-streaming responses,
the guardrail can run on the complete text before anything is returned to the
client, so blocking is meaningful — the response simply never goes out. For a
streaming response, tokens are already being emitted over the SSE connection as
they're generated; by the time enough text exists to scan for a leak, some of it
may already be on the wire and in the client's hands. So on the streaming path the
guardrail is necessarily a post-hoc audit — it can log a detected leak, but it
cannot retroactively un-send bytes the client has already received. This is an
inherent property of streaming, not a bug to be fixed by tuning the guardrail
config.

## Audit logging

A dedicated `pii.audit` logger, separate from application logs, emits structured
JSON for three operations: `MASK` (context id, entity count, entity types found),
`UNMASK` (context id, tokens found/replaced, whether validation passed), and
`PII_LEAK_DETECTED` (context id, entity count, entity types, logged at warning
level). Every entry carries an ISO-8601 UTC timestamp — notably, this is the one
place in the codebase where log lines have timestamps at all; the general
application logging format does not include them. Audit logging is gated by
`pii.audit.enabled` (default `true`) and never logs the original or masked text
itself — only counts and entity type names.

## Boot-time privacy validation

`ModelsConfig.validate_privacy_posture()` in rag-server refuses to start under two
conditions, both enforced at config-load time rather than left as a runtime risk:

1. **`pii.enabled: true` with a non-local embedding provider.** Since embeddings
   are never masked (by design, see above), allowing `pii.enabled` with a cloud
   embedding provider would defeat the entire point of the tier — the corpus text
   would go to the cloud embedding API in the clear regardless of what masking is
   configured for the LLM path. Config load raises rather than silently permitting
   this combination. The local set is `LOCAL_EMBEDDING_PROVIDERS = {"tei"}`.
2. **`pii.gliner.enabled: true` without the `gliner` package installed.** A missing
   optional dependency must not quietly downgrade detection to spaCy-only after
   the operator asked for GLiNER.

Both refusals happen once, at startup — there is no partial-degradation mode where
the server starts anyway with a warning.

## The judge gate is not a PII control

The eval service's LLM judge interpolates retrieved chunks and generated answers
verbatim into its prompt — masking is not applied there, because it would distort
the very text being judged. An eval run therefore ships *more* corpus content to
the judge than a normal query ships to the generation LLM, and it does so whether
`pii.enabled` is true or false.

That gate used to hang off `pii.enabled` plus a `pii.allow_cloud_judge` opt-out.
Both halves were wrong, and both are gone:

- Confidential content need not contain a single PII entity, so `pii.enabled` was
  never the right predicate for corpus egress.
- "Local" was inferred from a provider string via a `LOCAL_JUDGE_PROVIDERS` set
  that was in fact empty, so every judge counted as cloud regardless of where it
  actually ran.

The replacement lives in `data_policy` and is enforced by
`enforce_judge_boundary()` in **both** services' `infrastructure/config/models_config.py`
(the two services share no package, so the enum and the policy model are mirrored,
the same duplication as `LLMProvider`). Only the eval service actually calls it on
a judge — rag-server runs no judge — but the schema is declared in both so
`config.yml` validates identically either side, which is the same arrangement
`pii.allow_cloud_judge` had.

`ExecutionBoundary` is declared per model definition and describes the resolved
endpoint, never the provider name:

| value | meaning |
|---|---|
| `customer_managed` | a host or VPC the operator runs — local Docker, their own EC2 or K8s |
| `aws_managed` | Bedrock/SageMaker: inside the customer's AWS boundary, not on their host |
| `third_party` | OpenAI, Anthropic, any vendor-hosted API |

`DataPolicyConfig` holds the policy: `corpus_confidential` (default `true`),
`allowed_judge_boundaries` (an allow-list, default
`{customer_managed, aws_managed}`), and `eval_dataset_is_public` (default `false`
in code; the checked-in `config.yml` sets it `true`, which is what permits the
shipped third-party judge).

`enforce_judge_boundary()` returns early when the corpus is not confidential or the
eval dataset is declared public. Otherwise a boundary of `None` raises — **missing
boundary fails closed** — and so does any boundary outside the allow-list. It runs
twice: once at config load, and again in `resolve_judge_config()` at judge
resolution, so the object the runtime calls is the object that was checked.
